"""Validation shared by QA plan attachment and materialization writes."""

from __future__ import annotations

from collections.abc import Mapping
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
    qa_phase: Any = None,
) -> str:
    """Map the shared item QA binding error to the plan domain error.

    ``qa_phase`` decides which gate the binding is asked to reach: a
    post-merge phase binds where its own acceptance runs rather than at a
    verification gate. Dropping it here made every attachment read as
    verification, so a post-deploy plan could not be attached at all on a
    workflow whose item QA is an optional attachment.
    """
    try:
        transition, _workflow = validate_item_qa_transition(
            conn,
            item_id=int(item_id),
            transition_id=transition_id,
            plan_id=plan_id,
            qa_phase=qa_phase,
        )
    except QaWorkflowBindingError as exc:
        raise QaPlanError(str(exc)) from exc
    return transition


def validate_attached_item_transition(
    conn: Any,
    *,
    item_id: int,
    transition_id: Any,
    attachments: Mapping[int, Mapping[str, Any]],
) -> str:
    """Validate a transition and every attached plan's enforcement identity.

    Each attachment is judged under the ``qa_phase`` it was stored with.
    Reading them all as verification re-asked a post-deploy plan for a
    pre-merge gate it was never bound to, so an item that attached one at
    its release wait could attach it but never materialize it: the same
    transition the attach accepted came back with "no reachable
    qa_verification gate".
    """
    if not attachments:
        return validate_item_transition(
            conn,
            item_id=int(item_id),
            transition_id=transition_id,
        )
    transition = transition_id
    for plan_id, attachment in attachments.items():
        transition = validate_item_transition(
            conn,
            item_id=int(item_id),
            transition_id=transition,
            plan_id=int(plan_id),
            qa_phase=(attachment or {}).get("qa_phase"),
        )
    return transition


__all__ = [
    "require_plan_cases",
    "validate_attached_item_transition",
    "validate_item_transition",
]
