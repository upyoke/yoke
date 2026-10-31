"""Durable machine-local writer pause for local and self-host exports.

PostgreSQL refuses every source connection until explicit Resume. A durable
marker owns the frozen copy used for export and paused authentication.
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

_RESUMING: ContextVar[bool] = ContextVar("universe_resuming", default=False)
_ALLOWED: ContextVar[bool] = ContextVar("universe_pause_owner", default=False)
_OPERATION: ContextVar[str | None] = ContextVar(
    "universe_pause_operation", default=None
)


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
    if _OPERATION.get() == str(target):
        yield
        return
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
                deadline = time.monotonic() + 600
                while True:
                    try:
                        platform_file_lock.acquire_exclusive_nonblocking(descriptor)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise UniversePausedError(
                                compose_refusal(
                                    "universe_startup_wait_timeout: startup waited for an active source operation",
                                    recovery="finish or recover the source export, then restart the server; the source pause remains unchanged",
                                )
                            ) from None
                        time.sleep(0.05)
            acquired = True
        except (BlockingIOError, OSError) as exc:
            raise UniversePausedError(
                compose_refusal(
                    "universe_source_busy: another export or resume owns the source",
                    recovery="wait for that operation to finish, then retry",
                )
            ) from exc
        token = _OPERATION.set(str(target))
        try:
            yield
        finally:
            _OPERATION.reset(token)
    finally:
        if acquired:
            platform_file_lock.release_exclusive(descriptor)
        os.close(descriptor)


@contextmanager
def startup_access(dsn: str):
    """Serialize internal startup reads without reopening application admission."""
    from yoke_core.domain.universe_startup_lock import hosted_tenant_container_process

    if hosted_tenant_container_process():
        yield
        return
    with operation(dsn, wait=True), pause_owner():
        if is_paused(dsn):
            state = json.loads(_marker(dsn).read_text())
            frozen = state.get("database_pause")
            if frozen and not frozen["ready"]:
                from yoke_core.domain import universe_database_pause as database

                database.freeze(dsn, frozen)
                _save(_marker(dsn), state)
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
        postgres_connection_reuse,
        universe_source_services,
    )

    from yoke_core.domain import universe_database_pause as database

    marker = _marker(dsn)
    try:
        state = (
            json.loads(marker.read_text())
            if marker.exists()
            else universe_source_services.plan(dsn)
        )
        if "database_pause" not in state:
            state["database_pause"] = database.plan(dsn)
        _save(marker, state)
        universe_source_services.stop(state)
        postgres_connection_reuse.close_idle_connections()
        database.freeze(dsn, state["database_pause"], timeout_s=timeout_s)
        _save(marker, state)
        database.confirm(dsn, state["database_pause"])
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

    from yoke_core.domain import universe_database_pause as database

    with operation(dsn):
        marker = _marker(dsn)
        state = json.loads(marker.read_text()) if marker.exists() else {}
        frozen = state.get("database_pause")
        token = _RESUMING.set(True)
        try:
            if frozen:
                # Persist before reopening, so a failed Resume rebuilds the copy.
                frozen["ready"] = False
                _save(marker, state)
                database.reopen(dsn, frozen)
            with pause_owner(), db_backend.connect_psycopg(dsn) as conn:
                conn.execute("SELECT 1")
            with pause_owner():
                yield
            universe_source_services.start(state)
            if frozen:
                database.cleanup(dsn, frozen)
            marker.unlink(missing_ok=True)
            postgres_connection_reuse.close_idle_connections()
        except BaseException as exc:
            recovery_state = "source admission could not be confirmed"
            if frozen:
                try:
                    database.freeze(dsn, frozen)
                    _save(marker, state)
                    recovery_state = "source connections are fenced again"
                except Exception:
                    recovery_state = "source fencing or frozen-copy recovery failed; stop writers and check database administration access"
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise UniversePausedError(
                compose_refusal(
                    f"universe_resume_failed: Resume did not finish; {recovery_state}",
                    recovery="check database availability, relay and pause storage, then retry `yoke universe resume`; writes accepted during Resume are retained",
                )
            ) from exc
        finally:
            _RESUMING.reset(token)


def _save(marker, state):
    marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=marker.parent, prefix=".pause-")
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(state, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker)
        directory = os.open(marker.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def connection_dsn(dsn):
    require_running(dsn)
    if _ALLOWED.get() and not _RESUMING.get() and is_paused(dsn):
        from yoke_core.domain.universe_database_pause import read_dsn

        state = json.loads(_marker(dsn).read_text()).get("database_pause")
        if state:
            return read_dsn(dsn, state)
    return dsn


def export_source(dsn):
    from yoke_core.domain import universe_database_pause as database

    state = json.loads(_marker(dsn).read_text())["database_pause"]
    database.confirm(dsn, state)
    return database.read_dsn(dsn, state), {
        "database": state["name"],
        "database_oid": state["oid"],
    }


def resume(dsn: str) -> dict:
    with resuming_source(dsn):
        pass
    return {"resumed": True}
