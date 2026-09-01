"""Validation shared by QA plan attachment and materialization writes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder
from yoke_core.domain.qa_workflow_binding_validation import (
    QaWorkflowBindingError,
    validate_item_qa_transition,
)


def require_plan_cases(conn: Any, plan_id: int) -> None:
    """Refuse plans that cannot materialize any QA requirements."""
    marker = _placeholder(conn)
    row = query_one(
        conn,
        f"SELECT 1 FROM qa_plan_cases WHERE plan_id={marker} LIMIT 1",
        (int(plan_id),),
    )
    if row is None:
        raise QaPlanError(
            f"QA plan {plan_id} has no cases and cannot be attached or materialized"
        )


def validate_item_transition(
    conn: Any,
    *,
    item_id: int,
    transition_id: Any,
    plan_id: Any = None,
) -> str:
    """Map the shared item QA binding error to the plan domain error."""
    try:
        transition, _workflow = validate_item_qa_transition(
            conn,
            item_id=int(item_id),
            transition_id=transition_id,
            plan_id=plan_id,
        )
    except QaWorkflowBindingError as exc:
        raise QaPlanError(str(exc)) from exc
    return transition


def validate_attached_item_transition(
    conn: Any,
    *,
    item_id: int,
    transition_id: Any,
    plan_ids: Iterable[int],
) -> str:
    """Validate a transition and every attached plan's enforcement identity."""
    selected = tuple(int(plan_id) for plan_id in plan_ids)
    if not selected:
        return validate_item_transition(
            conn,
            item_id=int(item_id),
            transition_id=transition_id,
        )
    transition = transition_id
    for plan_id in selected:
        transition = validate_item_transition(
            conn,
            item_id=int(item_id),
            transition_id=transition,
            plan_id=plan_id,
        )
    return transition


__all__ = [
    "require_plan_cases",
    "validate_attached_item_transition",
    "validate_item_transition",
]
