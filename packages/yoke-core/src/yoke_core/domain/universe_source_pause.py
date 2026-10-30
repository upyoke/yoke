"""Durable machine-local writer pause for local and self-host exports.

Every db_backend acquisition checks the same database marker. Export and
Resume alone bypass it, so background services cannot reopen writer sessions.
The marker survives failed exports and server restarts until explicit Resume.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
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


@contextmanager
def operation(dsn: str, *, wait: bool = False):
    """Serialize export and resume across every source process."""
    from yoke_contracts import platform_file_lock

    target = _marker(dsn).with_suffix(".lock")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(target, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        try:
            try:
                platform_file_lock.acquire_exclusive_nonblocking(descriptor)
            except BlockingIOError:
                if not wait:
                    raise
                from yoke_contracts.designed_wait import announce_designed_wait

                announce_designed_wait(
                    "source export or resume to finish before startup",
                    max_wait_seconds=600,
                )
                platform_file_lock.acquire_exclusive(descriptor)
            acquired = True
        except (BlockingIOError, OSError) as exc:
            raise UniversePausedError(
                compose_refusal(
                    "universe_source_busy: another export or resume owns the source",
                    recovery="wait for that operation to finish, then retry",
                )
            ) from exc
        yield
    finally:
        if acquired:
            platform_file_lock.release_exclusive(descriptor)
        os.close(descriptor)


@contextmanager
def startup_access(dsn: str):
    """Serialize internal startup reads without reopening application admission."""
    from yoke_contracts.server_mode import SERVER_MODE_ENV, SERVER_MODE_SELF_HOST

    if os.environ.get(SERVER_MODE_ENV) != SERVER_MODE_SELF_HOST:
        yield
        return
    with operation(dsn, wait=True), pause_owner():
        yield


def check_connection(conn, dsn: str):
    """Close a socket that raced with the durable pause marker."""
    try:
        require_running(dsn)
    except UniversePausedError:
        conn.close()
        raise
    return conn


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
    from yoke_core.domain import (
        db_backend,
        postgres_connection_reuse,
        universe_source_services,
    )

    from yoke_core.domain.universe_startup_lock import application_sessions

    marker = _marker(dsn)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        services = (
            json.loads(marker.read_text())
            if marker.exists()
            else universe_source_services.plan(dsn)
        )
        if not marker.exists():
            descriptor, temporary = tempfile.mkstemp(
                dir=marker.parent, prefix=".pause-"
            )
            try:
                with os.fdopen(descriptor, "w") as handle:
                    json.dump(services, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, marker)
            finally:
                Path(temporary).unlink(missing_ok=True)
        directory = os.open(marker.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        universe_source_services.stop(services)
        postgres_connection_reuse.close_idle_connections()
        with pause_owner(), db_backend.connect_psycopg(dsn, autocommit=True) as conn:
            deadline = time.monotonic() + timeout_s
            while True:
                sessions = application_sessions(conn)
                if not sessions:
                    return
                for row in sessions:
                    conn.execute("SELECT pg_terminate_backend(%s)", (row[0],))
                if time.monotonic() >= deadline:
                    raise RuntimeError("client sessions did not drain")
                time.sleep(0.05)
    except universe_source_services.SourceServiceError as exc:
        raise UniversePausedError(str(exc)) from exc
    except Exception as exc:
        raise UniversePausedError(
            compose_refusal(
                "universe_pause_failed: could not stop and drain source writers; no move archive was produced",
                recovery="repair local storage or database session termination permission, retry export, or run `yoke universe resume` to restore writers",
            )
        ) from exc


@contextmanager
def resuming_source(dsn: str):
    """Remove the pause only after proving that the source can be reached."""
    from yoke_core.domain import (
        db_backend,
        postgres_connection_reuse,
        universe_source_services,
    )

    with operation(dsn):
        try:
            with pause_owner(), db_backend.connect_psycopg(dsn) as conn:
                conn.execute("SELECT 1")
            with pause_owner():
                yield
            marker = _marker(dsn)
            services = json.loads(marker.read_text()) if marker.exists() else {}
            universe_source_services.start(services)
            marker.unlink(missing_ok=True)
            postgres_connection_reuse.close_idle_connections()
        except UniversePausedError:
            raise
        except Exception as exc:
            raise UniversePausedError(
                compose_refusal(
                    "universe_resume_failed: the source could not resume; its pause remains in effect",
                    recovery="check database availability, the source relay and pause-marker permissions, then retry `yoke universe resume`",
                )
            ) from exc


def resume(dsn: str) -> dict:
    with resuming_source(dsn):
        pass
    return {"resumed": True}
