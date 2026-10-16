"""Settle a removed release member's QA cursors and their host ownership."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.qa_host_turns import cancel_host_waits
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_SQL,
    TERMINAL_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.schema_common import _table_exists


def abort_removed_member_executions(conn: Any, *, run_id: str, item_id: int) -> None:
    """Abort only this run/member's live executions in the caller's transaction.

    Cancel every waiting-line entry before releasing any reservation: releasing
    one host must never grant it to another cursor of the same removed member.
    Existing terminal evidence and other members' executions survive.
    """
    if not _table_exists(conn, "qa_plan_executions"):
        return
    rows = query_rows(
        conn,
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        f"AND deployment_member_item_id=%s AND state IN ({LIVE_PLAN_EXECUTION_SQL}) "
        "ORDER BY id",
        (run_id, item_id),
    )
    executions = [lock_plan_execution(conn, str(row["id"])) for row in rows]
    shared_rows = query_rows(
        conn,
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        f"AND deployment_member_item_id IS NULL AND state IN ({LIVE_PLAN_EXECUTION_SQL}) ORDER BY id",
        (run_id,),
    )
    from yoke_core.domain.deployment_qa_shared_plans import resolve_shared_subject

    for row in shared_rows:
        execution = lock_plan_execution(conn, str(row["id"]))
        target = execution.get("execution_target") or {}
        shared = (target.get("deployment") or {}).get("shared_plan")
        if not shared:
            continue
        retained = False
        others = query_rows(
            conn,
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s AND item_id<>%s",
            (run_id, item_id),
        )
        for other in others:
            try:
                resolve_shared_subject(
                    conn,
                    run_id=run_id,
                    stage_name=execution["deployment_stage"],
                    plan_id=shared["plan_id"],
                    member_item_id=int(other["item_id"]),
                    expected_target=target,
                    require_active=False,
                )
            except ValueError as exc:
                if not str(exc).startswith(
                    f"shared_plan_subject_unresolved: plan {shared['plan_id']} has 0 matching"
                ):
                    raise
            else:
                retained = True
                break
        if not retained:
            executions.append(execution)
    executions = [
        e for e in executions if e["state"] not in TERMINAL_PLAN_EXECUTION_STATES
    ]
    cancel_host_waits(conn, execution_ids=[str(e["id"]) for e in executions])
    for execution in executions:
        finish_plan_execution(
            conn,
            execution,
            state="aborted",
            reason="deployment-member-removed",
            commit=False,
        )


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
