"""Validation shared by QA plan attachment and materialization writes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_phase_boundary import (
    POST_MERGE_QA_PHASES,
    TERMINAL_DONE,
    is_pre_release_stage,
)
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder
from yoke_core.domain.qa_workflow_binding_validation import (
    QaWorkflowBindingError,
    validate_item_qa_transition,
)
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


class UnreachablePlanTargetError(QaPlanError):
    """A plan's persistent target cannot be reached at this transition."""


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


def plan_persistent_environment(
    conn: Any, plan: Mapping[str, Any]
) -> tuple[int, str] | None:
    """Return the persistent environment a plan is bound to, if any."""
    raw = plan.get("target_environment_id")
    if raw is None:
        return None
    environment_id = int(raw)
    row = query_one(
        conn,
        f"SELECT name FROM environments WHERE id={_placeholder(conn)}",
        (environment_id,),
    )
    if row is None:
        name = str(environment_id)
    elif hasattr(row, "keys"):
        name = str(row["name"])
    else:
        name = str(row[0])
    return environment_id, name


def item_delivery_environment_id(conn: Any, item_id: int) -> int | None:
    """The persistent environment this item's completion flow delivers to."""
    from yoke_core.domain.deployment_item_flow_resolution import (
        item_completion_flow,
    )

    flow_id = str(item_completion_flow(conn, int(item_id)) or "").strip()
    if not flow_id:
        return None
    row = query_one(
        conn,
        "SELECT target_environment_id FROM deployment_flows "
        f"WHERE id={_placeholder(conn)}",
        (flow_id,),
    )
    if row is None:
        return None
    raw = (
        row["target_environment_id"] if hasattr(row, "keys") else row[0]
    )
    if raw is None:
        return None
    return int(raw)


def refuse_unreachable_plan_attachment(
    conn: Any,
    *,
    item_id: int,
    plan: Mapping[str, Any],
    transition_id: str,
    qa_phase: str,
    acknowledge: bool = False,
) -> None:
    """Refuse a plan bound to this item's delivery environment too early.

    A catalog plan bound to development still attaches at pre-merge when
    the item delivers somewhere else. Materialization must not call this:
    an attachment that already exists keeps its meaning. Acknowledgement
    is for a caller who knows the target is already reachable.
    """
    if acknowledge:
        return
    target = plan_persistent_environment(conn, plan)
    if target is None:
        return
    environment_id, environment_name = target
    delivery_id = item_delivery_environment_id(conn, int(item_id))
    if delivery_id is None or delivery_id != environment_id:
        return
    phase = str(qa_phase or "").strip() or "verification"
    if phase in POST_MERGE_QA_PHASES:
        return
    workflow = load_item_workflow_runtime(conn, int(item_id))
    transition = str(transition_id or "").strip()
    if not is_pre_release_stage(workflow, transition):
        return
    attach_at = delivery_redirect_stage(workflow) or TERMINAL_DONE
    plan_id = int(plan["id"])
    raise UnreachablePlanTargetError(
        f"QA plan {plan_id} is bound to persistent environment "
        f"{environment_name!r} and cannot be satisfied at pre-delivery "
        f"transition {transition!r}: that environment is given this item's "
        "revision only by a deployment run, which the item cannot enter "
        "while this attachment blocks close-out. Attach the same plan at "
        "the item's post-deploy transition: yoke qa item-plan attach "
        f"--item PREFIX-N --project P --plan-id {plan_id} "
        f"--transition {attach_at} --qa-phase post_deploy. A caller who "
        "knows this target is already reachable may pass "
        "acknowledge_unreachable_target."
    )


__all__ = [
    "UnreachablePlanTargetError",
    "item_delivery_environment_id",
    "plan_persistent_environment",
    "refuse_unreachable_plan_attachment",
    "require_plan_cases",
    "validate_attached_item_transition",
    "validate_item_transition",
]
