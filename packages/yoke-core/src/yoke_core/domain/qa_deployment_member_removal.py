"""Settle a removed release member's QA cursors and their host ownership."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.qa_host_turns import cancel_host_waits
from yoke_core.domain.qa_plan_execution_abort_reason import MEMBER_REMOVED_REASON
from yoke_core.domain.qa_plan_execution_abort_state import (
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
    conn: Any, *, run_id: str, item_ids: Iterable[int]
) -> tuple[frozenset[int], frozenset[int]]:
    """Abort only these removed members' live executions in the caller's transaction.

    Run after the members' rows are deleted. A shared execution is aborted
    too when no remaining member attaches its plan target. Cancel every
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
    for row in shared_rows:
        execution = lock_plan_execution(conn, str(row["id"]))
        target = execution.get("execution_target") or {}
        shared = (target.get("deployment") or {}).get("shared_plan")
        if shared and not _shared_target_retained(conn, run_id, execution, shared):
            executions.append(execution)
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
    request = owed_host_abort(conn, execution, reason=MEMBER_REMOVED_REASON)
    if (
        request is None
        and execution["state"] == "awaiting_agent_review"
        and execution.get("machine_lease_id")
    ):
        request = next(
            (
                {"ordinal": ordinal}
                for ordinal, case in enumerate(execution.get("roster") or [])
                if case.get("runner_id") == "agent_mission"
            ),
            None,
        )
    return None if request is None else {**request, "reason": MEMBER_REMOVED_REASON}


def _shared_target_retained(
    conn: Any, run_id: str, execution: dict, shared: dict
) -> bool:
    """Whether a remaining member still attaches this shared execution's target."""
    from yoke_core.domain.deployment_qa_shared_plans import resolve_shared_subject

    try:
        resolve_shared_subject(
            conn,
            run_id=run_id,
            stage_name=execution["deployment_stage"],
            plan_id=shared["plan_id"],
            expected_target=execution.get("execution_target") or {},
            require_active=False,
        )
    except ValueError as exc:
        if not str(exc).startswith(
            f"shared_plan_subject_unresolved: plan {shared['plan_id']} has 0 matching"
        ):
            raise
        return False
    return True


@presentation_operation
def _plan_still_attached(conn: Any, run_id: str, stage_name: str, plan_id: int) -> bool:
    """Resolve the group with shared peer facts, before any retraction writes.

    This read scope ends before the next member deletion so removed peers
    cannot keep an orphaned group alive through a cached membership answer.
    """
    from yoke_core.domain.deployment_qa_shared_plans import resolve_shared_subject

    try:
        resolve_shared_subject(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            plan_id=plan_id,
            require_active=False,
        )
    except ValueError as exc:
        return not str(exc).startswith(
            f"shared_plan_subject_unresolved: plan {plan_id} has 0 matching"
        )
    return True


def retract_orphaned_shared_copies(conn: Any, *, run_id: str, reason: str) -> list[int]:
    """Retract unsettled shared-group rows whose plan no remaining member attaches.

    Run after the member row is deleted. A group another member still attaches
    keeps its rows; an orphaned group would otherwise stay a run-wide blocker.
    """
    from yoke_core.domain.deployment_qa_shared_plans import shared_target_identity
    from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
    from yoke_core.domain.qa_plan_attachment_retract import retract_requirements

    if not _table_exists(conn, "qa_requirements"):
        return []
    rows = query_rows(
        conn,
        "SELECT id,deployment_stage,plan_id,execution_target_json FROM qa_requirements "
        "WHERE deployment_run_id=%s AND deployment_member_item_id IS NULL "
        f"AND plan_id IS NOT NULL AND NOT {settled_obligation_sql(conn)} ORDER BY id",
        (run_id,),
    )
    groups: dict[tuple[str, int], list[int]] = {}
    for row in rows:
        if shared_target_identity(row["execution_target_json"]):
            key = (str(row["deployment_stage"]), int(row["plan_id"]))
            groups.setdefault(key, []).append(int(row["id"]))
    ids = [
        requirement_id
        for (stage_name, plan_id), members in groups.items()
        if not _plan_still_attached(conn, run_id, stage_name, plan_id)
        for requirement_id in members
    ]
    retract_requirements(conn, ids, reason=reason, source="operator")
    return ids
