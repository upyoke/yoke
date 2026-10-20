"""The one deployment-run row lock, bounded so no request queues behind it.

Every write that serializes on a run takes the row through :func:`lock_run`,
which waits at most :data:`RUN_ROW_LOCK_TIMEOUT_MS` and then refuses as
``run_busy``, naming the holder and its age. An unbounded wait is worse than a
refusal: on 2026-10-20 materialize transactions held one run row for up to
thirty minutes while seven requests queued behind it, each from a client that
had already given up at its own response timeout. A refused caller retries on
its own schedule -- the deploy driver on its next check, ``yoke watch``
wrappers with backoff -- instead of holding a backend that nobody reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings

_RUN_MEMBERSHIP_LOCK_RETRIES = 5
_BOUNDED_WRITE = ContextVar("deployment_bounded_write", default=False)

#: How long a caller lets the run row settle before refusing. Long enough to
#: ride out an ordinary concurrent mutation, far short of any client's
#: response timeout, so the refusal reaches a caller that is still listening.
RUN_ROW_LOCK_TIMEOUT_MS = 2000

#: The function error code, and the first word of every refusal message, for
#: a run row that stayed locked past the bound.
RUN_BUSY_CODE = "run_busy"

_LOCK_SAVEPOINT = "yoke_run_row_lock"


def _select_status(conn, run_id: str, suffix: str) -> Optional[str]:
    row = conn.execute(
        f"SELECT status FROM deployment_runs WHERE id=%s{suffix}",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["status"] if hasattr(row, "keys") else row[0])


def lock_run(conn, run_id: str) -> Optional[str]:
    """Take every lock a run-row write needs, or refuse as ``run_busy``.

    Returns the run's status, or ``None`` when the run does not exist. Raises
    :class:`DeploymentRunBusy` when the locks do not come free within
    :data:`RUN_ROW_LOCK_TIMEOUT_MS`. The attempt runs inside a savepoint so
    the timeout rolls back only the failed lock, leaving the caller's
    transaction usable for the diagnostic read; the caller's own
    ``lock_timeout`` is restored afterwards, so the bound covers this lock and
    nothing else the transaction goes on to take.

    The row lock alone is not enough. ``SELECT ... FOR UPDATE`` holds the
    table in ROW SHARE mode, which a SHARE-mode holder or waiter does not
    block, but the caller's ``UPDATE`` then needs ROW EXCLUSIVE, which it
    does. Taking ROW EXCLUSIVE here, under the same bound, leaves the write
    nothing further to wait for; otherwise it waited outside this savepoint
    and its lock timeout escaped as a raw ``LockNotAvailable``.
    """
    if not db_backend.connection_is_postgres(conn):
        return _select_status(conn, run_id, "")

    import psycopg

    previous = conn.execute("SELECT current_setting('lock_timeout')").fetchone()[0]
    conn.execute(f"SAVEPOINT {_LOCK_SAVEPOINT}")
    try:
        conn.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            (f"{RUN_ROW_LOCK_TIMEOUT_MS}ms",),
        )
        conn.execute("LOCK TABLE deployment_runs IN ROW EXCLUSIVE MODE")
        status = _select_status(conn, run_id, " FOR UPDATE")
    except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled):
        conn.execute(f"ROLLBACK TO SAVEPOINT {_LOCK_SAVEPOINT}")
        raise DeploymentRunBusy(run_id, run_row_lock_holder(conn)) from None
    conn.execute(f"RELEASE SAVEPOINT {_LOCK_SAVEPOINT}")
    conn.execute("SELECT set_config('lock_timeout', %s, true)", (str(previous),))
    return status


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
        if _BOUNDED_WRITE.get():
            raise ValueError(
                f"deployment_membership_changed: run {run_id!r} changed while locking; "
                "the transaction was rolled back; re-drive the same run after its writer settles"
            )
    raise RuntimeError(
        f"deployment run '{run_id}' membership changed repeatedly while locking"
    )


@dataclass(frozen=True)
class RunRowLockHolder:
    """A backend holding a ``deployment_runs`` lock, as far as stats can say."""

    pid: int
    state: str
    age_seconds: int


class DeploymentRunBusy(RuntimeError):
    """The run row was not writable within the bound, and the caller must not wait.

    Not a ``ValueError``: handlers that turn a ``ValueError`` into their own
    refusal or a failed stage must let this pass, so function dispatch answers
    it everywhere with the one ``run_busy`` code callers retry on.
    """

    def __init__(self, run_id: str, holder: Optional[RunRowLockHolder]) -> None:
        self.run_id = run_id
        self.holder = holder
        super().__init__(format_run_busy_refusal(run_id, holder))


def format_run_busy_refusal(run_id: str, holder: Optional[RunRowLockHolder]) -> str:
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
        f"{RUN_BUSY_CODE}: deployment run {run_id!r} row was not free within "
        f"{RUN_ROW_LOCK_TIMEOUT_MS}ms: {who}. This request refused rather "
        "than queueing behind the holder. A holder "
        "reported as 'idle in transaction' is an abandoned client and is "
        "released by idle_in_transaction_session_timeout. Recover by retrying "
        "the same command once the holder finishes: the deploy driver retries "
        "on its next check and `yoke watch` wrappers retry with backoff on "
        f"their own; re-run `yoke watch deploy -- {run_id}` if its driver stopped."
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


@contextmanager
def bounded_run_write(conn, run_id: str):
    """Bound every item/run/target lock in one short admission transaction."""
    if not db_backend.connection_is_postgres(conn):
        yield
        return
    import psycopg

    conn.execute(
        "SELECT set_config('lock_timeout', %s, true)",
        (f"{RUN_ROW_LOCK_TIMEOUT_MS}ms",),
    )
    token = _BOUNDED_WRITE.set(True)
    try:
        yield
    except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled):
        conn.rollback()
        raise ValueError(
            f"deployment_start_lock_busy: run {run_id!r} could not acquire an item, run, "
            f"or target lock within {RUN_ROW_LOCK_TIMEOUT_MS}ms; this transaction was rolled back. "
            f"Read `yoke deployment-runs get {run_id}` and the live driver's capture, "
            "then re-drive the same run after its current writer settles."
        ) from None
    finally:
        _BOUNDED_WRITE.reset(token)


__all__ = [
    "RUN_BUSY_CODE",
    "RUN_ROW_LOCK_TIMEOUT_MS",
    "DeploymentRunBusy",
    "RunRowLockHolder",
    "bounded_run_write",
    "format_run_busy_refusal",
    "lock_run",
    "lock_run_with_stable_membership",
    "run_row_lock_holder",
]
