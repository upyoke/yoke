"""Keep a live walk alive while its session borrows the walk's host lease.

``yoke test-machine exec`` borrows the caller's own host lease instead of
acquiring one. When that lease belongs to the caller's walking mission, the
borrow is walk activity, so it refreshes the walk's heartbeat the way
``yoke qa mission host-command`` does. The execution is resolved from the
machine's active lease on the server; the client never names it.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.qa_plan_execution_lifecycle import heartbeat_plan_execution
from yoke_core.domain.qa_plan_execution_store import (
    lock_plan_execution,
    marker,
    same_owner,
)
from yoke_core.domain.qa_plan_host_leases import HOST_SET_REASON
from yoke_core.domain.schema_common import _table_exists

#: Walk states in which a host command is walk activity (host-command's states).
WALK_STATES = frozenset({"walking", "awaiting_walk_review"})


def lease_execution_id(conn: Any, lease: Any) -> str | None:
    """The plan execution holding *lease* as its driver or companion host."""
    if not _table_exists(conn, "qa_plan_executions"):
        return None
    p = marker(conn)
    companion = (lease.reason or "").removeprefix(HOST_SET_REASON)
    row = conn.execute(
        f"SELECT id FROM qa_plan_executions WHERE test_machine_lease_id={p} OR id={p}",
        (lease.id, companion),
    ).fetchone()
    return None if row is None else str(row["id"])


def heartbeat_lease_execution(
    conn: Any,
    test_machine: str,
    *,
    actor_id: str | None,
    session_id: str,
) -> str | None:
    """Heartbeat the caller's walk holding *test_machine*; return its id.

    A machine with no active lease, a lease of another session, a lease no
    execution holds, another owner's execution, or an execution outside a
    walk heartbeats nothing and returns ``None``. The caller commits.
    """
    lease = active_claim(conn, host_claim_target(test_machine))
    if lease is None or lease.session_id != session_id:
        return None
    execution_id = lease_execution_id(conn, lease)
    if execution_id is None:
        return None
    execution = lock_plan_execution(conn, execution_id)
    if execution["state"] not in WALK_STATES or not same_owner(
        execution, actor_id=actor_id, session_id=session_id
    ):
        return None
    heartbeat_plan_execution(conn, execution)
    return execution_id


__all__ = ["WALK_STATES", "heartbeat_lease_execution", "lease_execution_id"]
