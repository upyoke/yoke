"""Transactional Postgres restore execution for portable universe data."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import psycopg
from psycopg import sql

from yoke_core.domain.universe_portability_common import (
    ArchiveTooLargeError,
    UniversePortabilityError,
    bounded_diagnostic_reader,
    subprocess_base_env,
    terminate,
    remaining_timeout,
)
from yoke_core.domain.universe_portability_restore_stream import (
    apply_restore_stream,
)


from yoke_core.domain.universe_portability_restore_contract import (
    restore_error_description,
)
from yoke_core.domain.universe_portability_restore_schema import (
    bounded_dsn,
    publish_restore_schema,
)


_log = logging.getLogger("yoke.universe.portability")


def restore_stream_worker(
    source: object,
    conn: object,
    *,
    target_schema: str,
    allowed_tables: set[str],
    allowed_sequences: set[str],
    max_sql_bytes: int,
    deadline: float,
    errors: list[BaseException],
) -> None:
    try:
        apply_restore_stream(
            source,
            conn,
            target_schema=target_schema,
            allowed_tables=allowed_tables,
            allowed_sequences=allowed_sequences,
            max_sql_bytes=max_sql_bytes,
            deadline=deadline,
        )
    except BaseException as exc:  # noqa: BLE001 - crosses a worker thread
        errors.append(exc)
    finally:
        source.close()  # type: ignore[attr-defined]


def suspend_restore_constraints(
    conn: object, target_schema: str,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Drop trusted FKs and suspend user triggers inside the load transaction."""
    foreign_keys = [
        (str(table), str(name), str(definition))
        for table, name, definition in conn.execute(  # type: ignore[attr-defined]
            "SELECT cls.relname, con.conname,"
            " pg_catalog.pg_get_constraintdef(con.oid, true)"
            " FROM pg_catalog.pg_constraint con"
            " JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid"
            " JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace"
            " WHERE ns.nspname = current_schema() AND con.contype = 'f'"
            " ORDER BY cls.relname, con.conname"
        ).fetchall()
    ]
    triggers = [
        (str(table), str(name), str(enabled))
        for table, name, enabled in conn.execute(  # type: ignore[attr-defined]
            "SELECT cls.relname, trig.tgname, trig.tgenabled"
            " FROM pg_catalog.pg_trigger trig"
            " JOIN pg_catalog.pg_class cls ON cls.oid = trig.tgrelid"
            " JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace"
            " WHERE ns.nspname = current_schema() AND NOT trig.tgisinternal"
            " ORDER BY cls.relname, trig.tgname"
        ).fetchall()
    ]
    for table, name, _definition in foreign_keys:
        conn.execute(  # type: ignore[attr-defined]
            sql.SQL("ALTER TABLE {}.{} DROP CONSTRAINT {}").format(
                sql.Identifier(target_schema),
                sql.Identifier(table),
                sql.Identifier(name),
            )
        )
    for table, name, enabled in triggers:
        if enabled != "D":
            conn.execute(  # type: ignore[attr-defined]
                sql.SQL("ALTER TABLE {}.{} DISABLE TRIGGER {}").format(
                    sql.Identifier(target_schema),
                    sql.Identifier(table),
                    sql.Identifier(name),
                )
            )
    return foreign_keys, triggers


def restore_constraints(
    conn: object,
    target_schema: str,
    foreign_keys: list[tuple[str, str, str]],
    triggers: list[tuple[str, str, str]],
) -> None:
    """Recreate trusted integrity objects, validating all imported rows."""
    for table, name, definition in foreign_keys:
        conn.execute(  # type: ignore[attr-defined]
            sql.SQL("ALTER TABLE {}.{} ADD CONSTRAINT {} {}").format(
                sql.Identifier(target_schema),
                sql.Identifier(table),
                sql.Identifier(name),
                sql.SQL(definition),
            )
        )
    modes = {
        "O": sql.SQL("ENABLE"),
        "D": sql.SQL("DISABLE"),
        "R": sql.SQL("ENABLE REPLICA"),
        "A": sql.SQL("ENABLE ALWAYS"),
    }
    for table, name, enabled in triggers:
        mode = modes.get(enabled)
        if mode is None:
            raise UniversePortabilityError(
                f"trusted trigger {table}.{name} has unknown mode {enabled!r}"
            )
        conn.execute(  # type: ignore[attr-defined]
            sql.SQL("ALTER TABLE {}.{} {} TRIGGER {}").format(
                sql.Identifier(target_schema),
                sql.Identifier(table),
                mode,
                sql.Identifier(name),
            )
        )


def quiesce_restore_worker(
    process: subprocess.Popen[bytes],
    worker: threading.Thread,
    connection: psycopg.Connection,
) -> bool:
    """Stop producer and COPY consumer before main-thread libpq teardown."""
    terminate(process)
    if process.stdout is not None:
        process.stdout.close()
    worker.join(timeout=2)
    if worker.is_alive() and not connection.closed:
        try:
            connection.cancel()
        except psycopg.Error:
            pass
        worker.join(timeout=2)
    if worker.is_alive() and not connection.closed:
        connection.close()
        worker.join(timeout=2)
    return not worker.is_alive()


def restore_via_libpq(
    *,
    executable: str,
    archive: Path,
    restore_list: Path,
    dsn: str,
    target_schema: str,
    allowed_tables: set[str],
    allowed_sequences: set[str],
    timeout_s: float,
    max_sql_bytes: int,
    finalize: Optional[Callable[[psycopg.Connection], None]],
) -> None:
    """Generate data-only output and apply its payload through strict libpq."""
    restore_cmd = [
        executable,
        "--file=-",
        "--data-only",
        "--no-owner",
        "--no-privileges",
        "--no-comments",
        "--no-publications",
        "--no-security-labels",
        "--no-subscriptions",
        "--schema=public",
        "--use-list",
        str(restore_list),
        str(archive),
    ]
    deadline = time.monotonic() + timeout_s
    connection = psycopg.connect(bounded_dsn(dsn, timeout_s, target_schema))
    foreign_keys: list[tuple[str, str, str]] = []
    triggers: list[tuple[str, str, str]] = []
    restore: subprocess.Popen[bytes] | None = None
    try:
        foreign_keys, triggers = suspend_restore_constraints(connection, target_schema)
        restore = subprocess.Popen(
            restore_cmd,
            env=subprocess_base_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        if restore is not None:
            terminate(restore)
        connection.rollback()
        connection.close()
        raise UniversePortabilityError(
            f"universe restore client could not start: {exc}"
        ) from exc
    except BaseException:
        connection.rollback()
        connection.close()
        raise
    assert restore is not None
    assert restore.stdout is not None and restore.stderr is not None
    stream_errors: list[BaseException] = []
    restore_stderr = bytearray()
    workers = (
        threading.Thread(
            target=restore_stream_worker,
            args=(restore.stdout, connection),
            kwargs={
                "target_schema": target_schema,
                "allowed_tables": allowed_tables,
                "allowed_sequences": allowed_sequences,
                "max_sql_bytes": max_sql_bytes,
                "deadline": deadline,
                "errors": stream_errors,
            },
            daemon=True,
        ),
        threading.Thread(
            target=bounded_diagnostic_reader,
            args=(restore.stderr, restore_stderr),
            daemon=True,
        ),
    )
    for worker in workers:
        worker.start()
    try:
        restore.wait(timeout=max(0.001, deadline - time.monotonic()))
        workers[0].join(timeout=max(0.001, deadline - time.monotonic()))
        if workers[0].is_alive():
            raise subprocess.TimeoutExpired(restore_cmd, timeout_s)
        if restore.returncode != 0 or stream_errors:
            connection.rollback()
        else:
            restore_constraints(connection, target_schema, foreign_keys, triggers)
            if finalize is not None:
                finalize(connection)
            timeout_ms = max(1, int(1000 * remaining_timeout(deadline, "schema swap")))
            # Leave time to roll back and remove staging if readers hold public.
            lock_timeout_ms = max(1, min(30_000, timeout_ms // 2))
            connection.execute(
                "SELECT set_config('statement_timeout', %s, true), "
                "set_config('lock_timeout', %s, true)",
                (str(timeout_ms), str(lock_timeout_ms)),
            )
            try:
                publish_restore_schema(connection, target_schema)
            except psycopg.Error as exc:
                raise UniversePortabilityError(
                    f"universe restore schema swap failed: {restore_error_description(exc)}; "
                    "close transactions using the destination and retry"
                ) from exc
            connection.commit()
    except subprocess.TimeoutExpired as exc:
        worker_stopped = quiesce_restore_worker(restore, workers[0], connection)
        if worker_stopped and not connection.closed:
            connection.rollback()
        raise UniversePortabilityError(
            f"universe restore timed out after {timeout_s}s"
        ) from exc
    except BaseException:
        connection.rollback()
        raise
    finally:
        terminate(restore)
        if workers[0].is_alive():
            quiesce_restore_worker(restore, workers[0], connection)
        for worker in workers:
            worker.join(timeout=5)
        if not connection.closed:
            connection.close()
    if stream_errors:
        error = stream_errors[0]
        if isinstance(error, (ArchiveTooLargeError, UniversePortabilityError)):
            raise error
        safe_error = UniversePortabilityError(restore_error_description(error))
        _log.error(
            "universe restore stream failed",
            exc_info=(type(safe_error), safe_error, error.__traceback__),
        )
        raise UniversePortabilityError(
            f"universe restore stream failed: {safe_error}; correct the cause and retry"
        ) from error
    if restore.returncode != 0:
        diagnostic = bytes(restore_stderr).decode("utf-8", errors="replace")
        diagnostic = "\n".join(diagnostic.strip().splitlines()[-12:])
        _log.error(
            "portable universe restore failed generator_rc=%s; stderr tail:\n%s",
            restore.returncode,
            diagnostic or "<no stderr>",
        )
        raise UniversePortabilityError(
            f"universe restore pg_restore exited with status {restore.returncode}; "
            "check the restore log and verify or regenerate the archive"
        )


__all__ = [
    "quiesce_restore_worker",
    "restore_constraints",
    "restore_stream_worker",
    "restore_via_libpq",
    "suspend_restore_constraints",
]
