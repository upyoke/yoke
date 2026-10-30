"""Durable machine-local writer pause for local and self-host exports.

Every db_backend acquisition checks the same database marker. Export and
Resume alone bypass it, so background services cannot reopen writer sessions.
The marker survives failed exports and server restarts until explicit Resume.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from yoke_contracts.machine_config.paths import yoke_home
from yoke_contracts.refusal_recovery import compose_refusal

_ALLOWED: ContextVar[bool] = ContextVar("universe_pause_owner", default=False)


class UniversePausedError(RuntimeError):
    """The source is paused or could not drain safely."""


def _marker(dsn: str) -> Path:
    from psycopg.conninfo import conninfo_to_dict

    values = conninfo_to_dict(dsn)
    identity = {
        key: values.get(key, "")
        for key in ("host", "hostaddr", "port", "dbname", "service")
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return yoke_home() / "universe-pauses" / (digest + ".paused")


def is_paused(dsn: str) -> bool:
    return _marker(dsn).exists()


def require_running(dsn: str) -> None:
    if not _ALLOWED.get() and is_paused(dsn):
        raise UniversePausedError(
            compose_refusal(
                "universe_source_paused: this source's writers are stopped for a move",
                recovery="run `yoke universe resume` against the source when it may write again",
            )
        )


@contextmanager
def pause_owner():
    """Permit only the explicit export/resume operation to open the source."""
    token = _ALLOWED.set(True)
    try:
        yield
    finally:
        _ALLOWED.reset(token)


def pause(dsn: str, *, timeout_s: float = 30) -> None:
    """Persist refusal before terminating all other database client sessions."""
    from yoke_core.domain import db_backend, postgres_connection_reuse

    marker = _marker(dsn)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(marker.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        postgres_connection_reuse.close_idle_connections()
        with pause_owner(), db_backend.connect_psycopg(dsn, autocommit=True) as conn:
            deadline = time.monotonic() + timeout_s
            while True:
                sessions = conn.execute(
                    "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                    "AND pid<>pg_backend_pid() AND backend_type='client backend'"
                ).fetchall()
                if not sessions:
                    return
                for row in sessions:
                    conn.execute("SELECT pg_terminate_backend(%s)", (row[0],))
                if time.monotonic() >= deadline:
                    raise RuntimeError("client sessions did not drain")
                time.sleep(0.05)
    except Exception as exc:
        raise UniversePausedError(
            compose_refusal(
                "universe_pause_failed: could not stop and drain source writers; no move archive was produced",
                recovery="repair local storage or database session termination permission, retry export, or run `yoke universe resume` to restore writers",
            )
        ) from exc


def resume(dsn: str) -> dict:
    """Remove the pause only after proving that the source can be reached."""
    from yoke_core.domain import db_backend, postgres_connection_reuse

    with pause_owner(), db_backend.connect_psycopg(dsn) as conn:
        conn.execute("SELECT 1")
    marker = _marker(dsn)
    marker.unlink(missing_ok=True)
    postgres_connection_reuse.close_idle_connections()
    return {"resumed": True}
