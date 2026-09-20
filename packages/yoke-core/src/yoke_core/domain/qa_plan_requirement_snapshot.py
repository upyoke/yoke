"""Idempotent QA requirement writes for materialized plan cases.

What a plan case becomes is :mod:`qa_plan_case_definition`; this module is
only the two ways it reaches a row. Keeping the derivation there is what lets
:mod:`qa_plan_case_currency` answer whether a row is still current without
re-deriving the transform by hand, and it is why an insert and a refresh can
never drift apart in what they write.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Optional

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder
from yoke_core.domain.qa_events import emit_qa_requirement_event
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    require_case_target,
    target_digest,
)
from yoke_core.domain.qa_plan_case_definition import (
    case_target_subject,
    materialized_definition,
)


def require_existing_target(
    rows: Iterable[Mapping[str, Any]],
    *,
    execution_target: Mapping[str, Any],
    subject: str,
) -> list[int]:
    """Permit idempotent reuse only for rows bound to the exact target."""
    expected_json = canonical_target(execution_target)
    expected_digest = target_digest(execution_target)
    ids: list[int] = []
    for row in rows:
        requirement_id = int(row["id"])
        raw_target = row["execution_target_json"]
        stored_digest = str(row["execution_target_digest"] or "")
        if not raw_target or not stored_digest:
            raise QaPlanError(
                f"{subject} has legacy QA requirement {requirement_id} without "
                "an execution target; preserve that evidence and start a fresh "
                "deployment/plan execution, or use a sanctioned requirement "
                "retirement or supersession operation before rematerializing"
            )
        try:
            stored_target = json.loads(str(raw_target))
        except (TypeError, ValueError) as exc:
            raise QaPlanError(
                f"{subject} has invalid target evidence on QA requirement "
                f"{requirement_id}; preserve it and use sanctioned retirement "
                "or supersession before rematerializing"
            ) from exc
        if (
            not isinstance(stored_target, dict)
            or canonical_target(stored_target) != expected_json
            or stored_digest != expected_digest
            or target_digest(stored_target) != stored_digest
        ):
            raise QaPlanError(
                f"{subject} has QA requirement {requirement_id} bound to a "
                "different execution target; do not reuse it—start a fresh "
                "deployment/plan execution or use sanctioned retirement or "
                "supersession before rematerializing"
            )
        ids.append(requirement_id)
    return ids


def require_requirement_id_target(
    conn: Any,
    *,
    requirement_id: int,
    execution_target: Mapping[str, Any],
    subject: str,
) -> int:
    """Validate the winner of a concurrent idempotent insert."""
    marker = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT id,execution_target_json,execution_target_digest "
        f"FROM qa_requirements WHERE id={marker}",
        (int(requirement_id),),
    )
    if row is None:
        raise QaPlanError(f"QA requirement {requirement_id} disappeared")
    return require_existing_target(
        [row],
        execution_target=execution_target,
        subject=subject,
    )[0]


def insert_requirement(
    conn: Any,
    *,
    item_id: Optional[int] = None,
    deployment_run_id: Optional[str] = None,
    deployment_stage: Optional[str] = None,
    deployment_member_item_id: Optional[int] = None,
    transition_id: Optional[str] = None,
    plan: Any,
    attachment: dict,
    case: Any,
    baseline: Optional[str],
    baseline_position: int,
    now: str,
    execution_target: dict[str, Any],
) -> Optional[int]:
    """Insert one immutable plan-case snapshot, returning its new id."""
    marker = _placeholder(conn)
    definition = materialized_definition(
        plan=plan,
        case=case,
        qa_phase=str(attachment["qa_phase"]),
        baseline=baseline,
        baseline_position=baseline_position,
        transition_id=transition_id,
        execution_target=execution_target,
    )
    require_case_target(case_target_subject(case, definition), execution_target)
    subject = {
        "item_id": item_id,
        "deployment_run_id": deployment_run_id,
        "deployment_stage": deployment_stage,
        "deployment_member_item_id": deployment_member_item_id,
    }
    columns = (*subject, *definition, "created_at")
    values = (*subject.values(), *definition.values(), now)
    row = conn.execute(
        f"INSERT INTO qa_requirements({', '.join(columns)}) "
        f"VALUES ({', '.join([marker] * len(values))}) "
        "ON CONFLICT DO NOTHING RETURNING id",
        values,
    ).fetchone()
    if row is None:
        return None
    requirement_id = int(row["id"] if isinstance(row, dict) else row[0])
    # The snapshot rides a transaction its caller commits — the lifecycle
    # preflight materializes with commit=False so the rows land with the
    # transition. Transactional emission keeps the creation event on that
    # same transaction, so no materialized requirement can exist without it.
    emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name="QARequirementCreated",
        requirement_id=requirement_id,
        qa_kind="plan_case",
        qa_phase=str(attachment["qa_phase"]),
        source="flow_derived",
        target_row={
            "item_id": item_id,
            "epic_id": None,
            "task_num": None,
            "deployment_run_id": deployment_run_id,
        },
        transactional=True,
    )
    return requirement_id


def refresh_requirement(
    conn: Any,
    *,
    requirement_id: int,
    transition_id: Optional[str],
    plan: Any,
    attachment: dict,
    case: Any,
    baseline: Optional[str],
    baseline_position: int,
    execution_target: dict[str, Any],
) -> dict[str, Any]:
    """Refresh a materialized case without severing its run history.

    This is the one write that brings a live row back to its plan's current
    text, and it reaches every executable column — instructions and
    expected_outcome included — because it writes the derivation whole rather
    than going through the narrow ``qa.requirement.update`` allowlist.
    """
    marker = _placeholder(conn)
    definition = materialized_definition(
        plan=plan,
        case=case,
        qa_phase=str(attachment["qa_phase"]),
        baseline=baseline,
        baseline_position=baseline_position,
        transition_id=transition_id,
        execution_target=execution_target,
    )
    require_case_target(case_target_subject(case, definition), execution_target)
    assignments = ", ".join(f"{column}={marker}" for column in definition)
    conn.execute(
        f"UPDATE qa_requirements SET {assignments}, "
        "waived_at=NULL, waiver_rationale=NULL, waiver_source=NULL "
        f"WHERE id={marker}",
        (*definition.values(), int(requirement_id)),
    )
    # Returned so the caller can carry the same derivation onward — an
    # admitted copy of this row needs the body that was just written, not a
    # second derivation of it.
    return definition


def existing_requirement_id(
    conn: Any,
    *,
    item_id: Optional[int] = None,
    deployment_run_id: Optional[str] = None,
    deployment_stage: Optional[str] = None,
    deployment_member_item_id: Optional[int] = None,
    plan_id: int,
    case_key: str,
    baseline: Optional[str],
    transition_id: Optional[str] = None,
    execution_target_digest: Optional[str] = None,
) -> Optional[int]:
    """Resolve the snapshot that won a concurrent idempotent insert."""
    marker = _placeholder(conn)
    if (item_id is None) == (deployment_run_id is None):
        raise ValueError("exactly one of item_id or deployment_run_id is required")
    subject_column = "item_id" if item_id is not None else "deployment_run_id"
    subject_value: int | str = (
        int(item_id) if item_id is not None else str(deployment_run_id)
    )
    target_clause = (
        f"AND execution_target_digest={marker} "
        if execution_target_digest is not None
        else ""
    )
    params: tuple[Any, ...] = (
        subject_value, deployment_stage or "", deployment_member_item_id or 0,
        plan_id, case_key, baseline or "", transition_id or "",
    )
    if execution_target_digest is not None:
        params += (execution_target_digest,)
    row = query_one(
        conn,
        "SELECT id FROM qa_requirements "
        f"WHERE {subject_column}={marker} "
        f"AND COALESCE(deployment_stage, '')={marker} "
        f"AND COALESCE(deployment_member_item_id, 0)={marker} "
        f"AND plan_id={marker} "
        f"AND plan_case_key={marker} "
        f"AND COALESCE(host_baseline, '')={marker} "
        f"AND COALESCE(workflow_transition_id, '')={marker} "
        f"{target_clause}",
        params,
    )
    return int(row["id"]) if row is not None else None


__all__ = [
    "existing_requirement_id",
    "insert_requirement",
    "refresh_requirement",
    "require_existing_target",
    "require_requirement_id_target",
]
