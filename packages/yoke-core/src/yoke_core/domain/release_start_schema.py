"""Bring the control-plane schema up to this release before its run starts.

A deploy driver connected straight to a database (``prod-db-admin``,
``stage-db-admin``, a local universe) dispatches every run operation
in-process, so the release's own code reads and writes that database before
the release has booted anywhere. Boot is what adds a new release's additive
tables and columns, so without this step a release that adds a column fails
its own start on ``UndefinedColumn``.

This step runs boot's creation phase — tables, indexes and additive columns,
the same code — before the first such call, as the role that owns the
database's tables, so a new table stays convergeable by the serving build. Ordered migration history and its
restore points stay with boot. The serving build tolerates what this adds,
and the fleet preflight converges a copy of every live database through the
same boot sequence before any release, which is the proof the phase is safe.

A driver relaying through HTTPS runs no release code against the database:
the serving build answers every call, so there is nothing to converge.

A run that already started converged at its first start, and its candidate
is frozen, so re-driving it converges nothing and reads only its start stamp.

Two drivers on one control plane converge the same database, so one driver
at a time holds the convergence lock
(:mod:`yoke_core.domain.release_start_schema_lock`). A converge that still
meets a concurrent creator, such as a booting server, retries: the rerun
finds the object present.
"""

from __future__ import annotations

from yoke_contracts.schema_authority import serving_build_authority
from yoke_core.domain.deployment_runs_lock import RUN_ROW_LOCK_TIMEOUT_MS
from yoke_core.domain.release_start_schema_lock import (
    ConvergenceLockHeld,
    holding_convergence_lock,
)

LOCK_UNAVAILABLE = "release_start_schema_lock_unavailable"
CONVERGENCE_FAILED = "release_start_schema_convergence_failed"

#: Catalog uniques a ``CREATE ... IF NOT EXISTS`` trips when another session
#: creates the same type or relation between its existence check and insert.
CONCURRENT_CREATION_CONSTRAINTS = frozenset(
    {"pg_type_typname_nsp_index", "pg_class_relname_nsp_index"}
)
CONCURRENT_CREATION_ATTEMPTS = 3


class ReleaseStartSchemaError(RuntimeError):
    """The release's additive schema could not be applied before its start."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def converge_release_start_schema(run_id: str) -> bool:
    """Apply the additive phase when this driver first starts a run in-process.

    Returns whether it ran. One driver at a time converges; a driver kept
    waiting past the lock's bound refuses naming the run that holds it
    (:mod:`yoke_core.domain.release_start_schema_lock`). Only missing objects are created, one table per transaction,
    and each statement waits at most :data:`RUN_ROW_LOCK_TIMEOUT_MS` for its
    table lock so serving requests never queue behind it. A busy table is
    retried with backoff and then refuses by name
    (:mod:`yoke_core.domain.schema_converge_statements`).
    """
    from yoke_cli.transport import https as https_transport

    if https_transport.resolve_https_connection() is not None:
        return False

    import psycopg

    from yoke_core.domain import db_helpers
    from yoke_core.domain.environment_bootstrap import universe_is_born_on
    from yoke_core.domain.schema_converge_statements import SchemaConvergeLockError

    recovery = (
        f"Nothing about {run_id} has started; re-drive it with "
        f"`yoke watch deploy -- {run_id}`."
    )
    try:
        with db_helpers.connect() as conn, serving_build_authority():
            if not universe_is_born_on(conn) or _already_started(conn, run_id):
                return False
            with holding_convergence_lock(conn, run_id):
                _converge_as_serving_owner(conn)
    except ConvergenceLockHeld as exc:
        raise ReleaseStartSchemaError(
            LOCK_UNAVAILABLE,
            f"{exc} and still held the release-start schema lock. Let that "
            "start finish first. " + recovery,
        ) from None
    except SchemaConvergeLockError as exc:
        raise ReleaseStartSchemaError(
            LOCK_UNAVAILABLE,
            f"applying this release's additive schema waited "
            f"{RUN_ROW_LOCK_TIMEOUT_MS}ms per attempt for a busy table: {exc} "
            + recovery,
        ) from None
    except psycopg.Error as exc:
        if _concurrent_creation(exc):
            raise ReleaseStartSchemaError(
                CONVERGENCE_FAILED,
                f"another process kept creating the same schema objects "
                f"through {CONCURRENT_CREATION_ATTEMPTS} attempts ({exc}). "
                "Nothing is wrong with the schema or its grants. " + recovery,
            ) from exc
        raise ReleaseStartSchemaError(
            CONVERGENCE_FAILED,
            f"applying this release's additive schema as the serving owner "
            f"failed ({exc}). Repair the named role grant, table or column, "
            "then rerun. " + recovery,
        ) from exc
    return True


__all__ = [
    "CONCURRENT_CREATION_ATTEMPTS",
    "CONCURRENT_CREATION_CONSTRAINTS",
    "CONVERGENCE_FAILED",
    "LOCK_UNAVAILABLE",
    "ReleaseStartSchemaError",
    "converge_release_start_schema",
]


def _already_started(conn, run_id: str) -> bool:
    """Whether *run_id* started before; its first start converged the schema."""
    row = conn.execute(
        "SELECT started_at FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    conn.commit()
    return row is not None and row[0] is not None


def _converge_as_serving_owner(conn) -> None:
    """Converge as the tables' owner, retrying a concurrent creation."""
    from yoke_core.domain.migration_fleet_ownership import acting_as_serving_owner
    from yoke_core.domain.schema_creation import converge_additive_schema

    for attempt in range(1, CONCURRENT_CREATION_ATTEMPTS + 1):
        conn.execute(f"SET lock_timeout = '{RUN_ROW_LOCK_TIMEOUT_MS}ms'")
        try:
            # Tables belong to their creator; create them as the role that
            # serves the database, never as the driver's admin role.
            with acting_as_serving_owner(conn):
                converge_additive_schema(conn)
            return
        except Exception as exc:
            if attempt == CONCURRENT_CREATION_ATTEMPTS or not _concurrent_creation(
                exc
            ):
                raise
            conn.rollback()


def _concurrent_creation(exc: BaseException) -> bool:
    """Whether *exc* is another session creating the same catalog object."""
    import psycopg

    diag = getattr(exc, "diag", None)
    return (
        isinstance(exc, psycopg.errors.UniqueViolation)
        and diag is not None
        and diag.constraint_name in CONCURRENT_CREATION_CONSTRAINTS
    )
