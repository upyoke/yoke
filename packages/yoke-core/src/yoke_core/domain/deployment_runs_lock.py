"""Row-lock primitives shared by deployment-run mutation commands.

Two shapes, and the difference matters. :func:`lock_run` waits: a mutation that
must serialize against every other mutation of the same run has nothing useful
to do until the row is its own. :func:`lock_run_bounded` refuses: a liveness
probe that waits is worse than one that skips, because the probe exists to
report motion and a blocked probe reports nothing at all. A deploy driver
heartbeat queued behind an abandoned transaction printed silence for eleven
minutes while its own watcher had no other progress signal to show.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings

_RUN_MEMBERSHIP_LOCK_RETRIES = 5

#: How long a non-waiting caller lets the run row settle before skipping. Long
#: enough to ride out an ordinary concurrent mutation, far short of the
#: heartbeat interval so a skipped tick is reported rather than merged into the
#: next one.
RUN_ROW_LOCK_TIMEOUT_MS = 2000

#: Leads every bounded-lock refusal, so a watcher can promote the line to the
#: user-facing stream by matching one string.
RUN_ROW_LOCK_BLOCKED_PREFIX = "deploy run row lock blocked:"

_LOCK_SAVEPOINT = "yoke_run_row_lock"


def lock_run(conn, run_id: str) -> Optional[str]:
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT status FROM deployment_runs WHERE id=%s{suffix}",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["status"] if hasattr(row, "keys") else row[0])


def _run_item_ids(conn, run_id: str) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return tuple(
        int(row["item_id"]) if hasattr(row, "keys") else int(row[0]) for row in rows
    )


def lock_run_with_stable_membership(
    conn,
    run_id: str,
) -> tuple[Optional[str], tuple[int, ...]]:
    """Lock workflow bindings before the run and reject a stale member snapshot."""
    for _attempt in range(_RUN_MEMBERSHIP_LOCK_RETRIES):
        item_ids = _run_item_ids(conn, run_id)
        lock_item_workflow_bindings(conn, item_ids)
        status = lock_run(conn, run_id)
        if status is None:
            return None, ()
        if _run_item_ids(conn, run_id) == item_ids:
            return status, item_ids
        conn.rollback()
    raise RuntimeError(
        f"deployment run '{run_id}' membership changed repeatedly while locking"
    )


@dataclass(frozen=True)
class RunRowLockHolder:
    """A backend holding a ``deployment_runs`` lock, as far as stats can say."""

    pid: int
    state: str
    age_seconds: int


class DeploymentRunRowLockBusy(Exception):
    """The run row was not free within the bound, and the caller must not wait."""

    def __init__(self, run_id: str, holder: Optional[RunRowLockHolder]) -> None:
        self.run_id = run_id
        self.holder = holder
        super().__init__(format_run_row_lock_refusal(run_id, holder))


def format_run_row_lock_refusal(run_id: str, holder: Optional[RunRowLockHolder]) -> str:
    """Name who is holding the run row, for how long, and what happens next."""
    if holder is None:
        who = (
            "no other backend still holds a deployment_runs lock, so the "
            "contention cleared while this refusal was composed"
        )
    else:
        state = f" while {holder.state}" if holder.state else ""
        who = (
            f"pid {holder.pid} has held a deployment_runs lock for "
            f"{holder.age_seconds}s{state}"
        )
    return (
        f"{RUN_ROW_LOCK_BLOCKED_PREFIX} deployment run {run_id!r} row was not "
        f"free within {RUN_ROW_LOCK_TIMEOUT_MS}ms: {who}. Nothing was written "
        "and this attempt is skipped rather than queued. A holder reported as "
        "'idle in transaction' is an abandoned client, not work in progress: "
        "its backend is bounded by idle_in_transaction_session_timeout and "
        f"releases on its own. Recover by re-running the same command "
        f"(`yoke watch deploy -- {run_id}` for a deploy driver), which "
        "re-attaches to this run rather than starting a second one."
    )


def run_row_lock_holder(conn) -> Optional[RunRowLockHolder]:
    """Describe the oldest other backend holding a ``deployment_runs`` lock.

    A diagnostic, never an authority: it names a holder rather than proving it
    is *the* blocker, and an unprivileged role sees other backends' pids but
    not their state. Any failure here returns ``None``, because a refusal that
    cannot describe its cause must still be raised.
    """
    try:
        row = conn.execute(
            "SELECT a.pid, COALESCE(a.state, ''), "
            "GREATEST(0, EXTRACT(EPOCH FROM "
            "(clock_timestamp() - a.state_change)))::int "
            "FROM pg_stat_activity a JOIN pg_locks l ON l.pid = a.pid "
            "WHERE l.relation = 'deployment_runs'::regclass "
            # pg_locks spans the cluster and its relation oids only mean
            # anything inside their own database, so an unfiltered read can
            # name a backend working on a different universe entirely.
            "AND l.database = "
            "(SELECT oid FROM pg_database WHERE datname = current_database()) "
            "AND a.pid <> pg_backend_pid() "
            "ORDER BY a.state_change ASC NULLS LAST LIMIT 1"
        ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return RunRowLockHolder(
        pid=int(row[0]), state=str(row[1] or ""), age_seconds=int(row[2] or 0)
    )


def lock_run_bounded(conn, run_id: str) -> Optional[str]:
    """Take the run row lock, or refuse by name instead of waiting for it.

    Raises :class:`DeploymentRunRowLockBusy` when the row does not come free
    within :data:`RUN_ROW_LOCK_TIMEOUT_MS`. The attempt runs inside a savepoint
    so the timeout rolls back only the failed lock, leaving the caller's
    transaction usable for the diagnostic read and its own refusal reporting.
    """
    if not db_backend.connection_is_postgres(conn):
        return lock_run(conn, run_id)

    import psycopg

    conn.execute(f"SAVEPOINT {_LOCK_SAVEPOINT}")
    try:
        conn.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            (f"{RUN_ROW_LOCK_TIMEOUT_MS}ms",),
        )
        status = lock_run(conn, run_id)
    except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled):
        conn.execute(f"ROLLBACK TO SAVEPOINT {_LOCK_SAVEPOINT}")
        raise DeploymentRunRowLockBusy(run_id, run_row_lock_holder(conn)) from None
    conn.execute(f"RELEASE SAVEPOINT {_LOCK_SAVEPOINT}")
    return status


__all__ = [
    "RUN_ROW_LOCK_BLOCKED_PREFIX",
    "RUN_ROW_LOCK_TIMEOUT_MS",
    "DeploymentRunRowLockBusy",
    "RunRowLockHolder",
    "format_run_row_lock_refusal",
    "lock_run",
    "lock_run_bounded",
    "lock_run_with_stable_membership",
    "run_row_lock_holder",
]
