"""Ordered QA execution roster selection and cursor validation."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError


def ordered_plan_requirements(
    conn: Any,
    *,
    item_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
    deployment_stage: str | None = None,
    deployment_member_item_id: int | None = None,
    execution_target_digest: str | None = None,
) -> list[dict[str, Any]]:
    """Return server-authoritative execution order for one QA subject."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    if (item_id is None) == (deployment_run_id is None):
        raise QaPlanExecutionError("exactly one QA plan execution subject is required")
    if item_id is not None:
        where = f"item_id={marker} AND workflow_transition_id={marker}"
        params: tuple[Any, ...] = (int(item_id), str(transition_id))
        subject = f"{render_item_ref(conn, item_id)} transition {transition_id!r}"
    else:
        if deployment_member_item_id is not None and deployment_stage is None:
            raise QaPlanExecutionError("deployment member requires deployment stage")
        where = (
            f"deployment_run_id={marker} "
            f"AND COALESCE(deployment_stage,'')={marker} "
            f"AND COALESCE(deployment_member_item_id,0)={marker}"
        )
        params = (
            str(deployment_run_id),
            deployment_stage or "",
            deployment_member_item_id or 0,
        )
        if deployment_stage is not None:
            if not execution_target_digest:
                target_rows = conn.execute(
                    "SELECT DISTINCT execution_target_digest FROM qa_requirements "
                    f"WHERE {where} AND method_id IS NOT NULL",
                    params,
                ).fetchall()
                if len(target_rows) != 1 or not target_rows[0][0]:
                    raise QaPlanExecutionError(
                        "scoped deployment QA roster has ambiguous target history; "
                        "resolve it against the active stage receipt"
                    )
                execution_target_digest = str(target_rows[0][0])
            where += f" AND execution_target_digest={marker}"
            params += (execution_target_digest,)
        subject = (
            f"deployment run {deployment_run_id!r} stage "
            f"{deployment_stage!r} member {deployment_member_item_id!r}"
        )
    cursor = conn.execute(
        "SELECT id AS requirement_id,plan_id,plan_case_key AS case_key,"
        "case_position,baseline_position,host_baseline,method_id,runner_id "
        f"FROM qa_requirements WHERE {where} "
        "AND method_id IS NOT NULL AND waived_at IS NULL "
        "ORDER BY CASE WHEN plan_id IS NULL THEN 0 ELSE 1 END,"
        "COALESCE(plan_id,0),case_position,baseline_position,id",
        params,
    )
    names = [
        str(getattr(column, "name", None) or column[0]) for column in cursor.description
    ]
    requirements = [
        dict(row) if hasattr(row, "keys") else dict(zip(names, row))
        for row in cursor.fetchall()
    ]
    if not requirements:
        raise QaPlanExecutionError(f"{subject} has no materialized QA cases")
    for rank, row in enumerate(requirements, start=1):
        requirement_id = int(row["requirement_id"])
        plan_id = int(row["plan_id"]) if row["plan_id"] is not None else None
        if not str(row["runner_id"] or "").strip():
            raise QaPlanExecutionError(
                f"materialized QA case {requirement_id} has an incomplete "
                "execution snapshot; apply the QA requirement snapshot migration"
            )
        if plan_id is None:
            # A case belonging to no plan was never given a position inside
            # one, and inventing a plan to hold it would make the roster
            # claim an ordering authority nothing declared. Its order is the
            # selection's own: plan-less cases first, oldest row first, which
            # is stable for the same set of cases and is what the immutable
            # execution snapshot records. Only a case that does belong to a
            # plan still owes the positions that plan assigned it.
            case_position, baseline_position = rank, 1
        elif row["case_position"] is None or row["baseline_position"] is None:
            raise QaPlanExecutionError(
                f"materialized QA case {requirement_id} has an incomplete "
                "execution snapshot; apply the QA requirement snapshot migration"
            )
        else:
            case_position = int(row["case_position"])
            baseline_position = int(row["baseline_position"])
        row.update(
            requirement_id=requirement_id,
            plan_id=plan_id,
            case_position=case_position,
            baseline_position=baseline_position,
        )
    return requirements


def validate_roster_machine(
    conn: Any, roster: list[dict[str, Any]], machine: str | None
) -> None:
    from yoke_core.domain.machine_qa_case_machine import (
        require_registered_machine,
        resolve_plan_machine,
    )

    selected = resolve_plan_machine(roster, machine)
    projects = {
        int(row["project_id"])
        for row in roster
        if row.get("runner_id") in {"host_control", "agent_mission"}
    }
    for project_id in projects:
        require_registered_machine(
            conn,
            project_id=project_id,
            machine=selected,
            subject="run pin" if machine else "case constraint",
        )


def expected_plan_case(
    execution: Mapping[str, Any],
    *,
    ordinal: int,
    requirement_id: int,
    allow_replay: bool = False,
) -> dict[str, Any]:
    """Validate an ordinal and return its immutable roster case."""
    cursor = int(execution["cursor_ordinal"])
    if ordinal != cursor and not (allow_replay and ordinal < cursor):
        raise QaPlanExecutionStateError(
            f"QA plan execution expects ordinal {cursor}, not {ordinal}"
        )
    roster = execution["roster"]
    if ordinal < 0 or ordinal >= len(roster):
        raise QaPlanExecutionStateError("QA plan execution ordinal is out of range")
    case = dict(roster[ordinal])
    if int(case["requirement_id"]) != int(requirement_id):
        raise QaPlanExecutionStateError(
            "QA plan execution ordinal targets a different requirement"
        )
    return case


__all__ = [
    "expected_plan_case",
    "ordered_plan_requirements",
    "validate_roster_machine",
]
