"""Settle a removed release member's QA cursors and their host ownership."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_host_turns import cancel_host_waits
from yoke_core.domain.qa_plan_execution_abort_reason import MEMBER_REMOVED_REASON
from yoke_core.domain.qa_plan_execution_abort_state import (
    mission_walk_owed,
    owed_host_abort,
    record_abort_request,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_SQL,
    TERMINAL_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.schema_common import _table_exists


def abort_removed_member_executions(
    conn: Any,
    *,
    run_id: str,
    item_ids: Iterable[int],
) -> tuple[frozenset[int], frozenset[int]]:
    """Abort only these removed members' live executions in the caller's transaction.

    Run after the members' rows are deleted. A plan group's execution is
    aborted too when no remaining member attaches its plan. Cancel every
    waiting-line entry before releasing any reservation: releasing one host
    must never grant it to another cursor of the same removed members.
    Existing terminal evidence and other members' executions survive.

    An execution whose held host may be dirty is not finished here: it keeps
    custody and heartbeat authority under a recorded cooperative abort, and
    releases its host only after cleanup proof (`removal_cleanup_request`).
    Returns the removed members whose QA this call stopped, and those whose
    stopped execution still holds its host for cleanup. A shared execution
    counts for every removed member.
    """
    ids = sorted({int(value) for value in item_ids})
    if not ids or not _table_exists(conn, "qa_plan_executions"):
        return frozenset(), frozenset()
    rows = query_rows(
        conn,
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        f"AND deployment_member_item_id=ANY(%s) AND state IN ({LIVE_PLAN_EXECUTION_SQL}) "
        "ORDER BY id",
        (run_id, ids),
    )
    executions = [lock_plan_execution(conn, str(row["id"])) for row in rows]
    shared_rows = query_rows(
        conn,
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        f"AND deployment_member_item_id IS NULL AND state IN ({LIVE_PLAN_EXECUTION_SQL}) ORDER BY id",
        (run_id,),
    )
    shared_executions = [
        execution
        for execution in (
            lock_plan_execution(conn, str(row["id"])) for row in shared_rows
        )
        if ((execution.get("execution_target") or {}).get("deployment") or {}).get(
            "shared_plan"
        )
    ]
    if shared_executions:
        from yoke_core.domain.deployment_qa_plan_groups import (
            group_marker,
            unattached_open_groups,
        )

        orphaned = {group.group_id for group in unattached_open_groups(conn, run_id)}
        executions.extend(
            execution
            for execution in shared_executions
            if str(group_marker(execution["execution_target"])["group_id"]) in orphaned
        )
    executions = [
        e for e in executions if e["state"] not in TERMINAL_PLAN_EXECUTION_STATES
    ]
    cancel_host_waits(conn, execution_ids=[str(e["id"]) for e in executions])
    cleaning = []
    for execution in executions:
        request = removal_cleanup_request(conn, execution)
        if request is not None:
            record_abort_request(conn, execution, request)
            cleaning.append(execution)
            continue
        finish_plan_execution(
            conn,
            execution,
            state="aborted",
            reason=MEMBER_REMOVED_REASON,
            commit=False,
        )
    return _owners(executions, ids), _owners(cleaning, ids)


def _owners(executions: list[dict], removed: list[int]) -> frozenset[int]:
    """The removed members these executions belong to; a shared one is everyone's."""
    owners = {e.get("deployment_member_item_id") for e in executions}
    if None in owners:
        return frozenset(removed)
    return frozenset(int(owner) for owner in owners)


def removal_cleanup_request(conn: Any, execution: dict) -> dict | None:
    """The abort a removed execution's held host owes before release, or None.

    In-flight host_control work owes its restore proof; an awaiting
    agent_mission walk holding its machine owes its walk-end teardown. An
    earlier cancellation keeps its time and case but now names the removal.
    """
    request = owed_host_abort(
        conn, execution, reason=MEMBER_REMOVED_REASON
    ) or mission_walk_owed(conn, execution)
    return None if request is None else {**request, "reason": MEMBER_REMOVED_REASON}


def retract_orphaned_shared_copies(conn: Any, *, run_id: str, reason: str) -> list[int]:
    """Retract each open plan group no remaining member attaches.

    Run after the removed members' rows are deleted. Passed rows and closed
    groups are never touched; a later attacher gets a new group.
    """
    from yoke_core.domain.deployment_qa_plan_groups import retract_unattached_groups

    if not _table_exists(conn, "qa_requirements"):
        return []
    return retract_unattached_groups(conn, run_id, reason=reason, source="operator")
