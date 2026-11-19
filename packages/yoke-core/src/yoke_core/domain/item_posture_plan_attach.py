"""Attach the verification plan an item was filed with.

Plan selection stays a declaration on the item row (see
``item_posture_bindings``).  Filing is the one place that also attaches it:
the plan chosen at create (the project default or ``--verification-plan``)
becomes a live ``qa_plan_item_attachments`` row at the review transition, so
materialize and the dash verification gate see it with no manual attach.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.item_posture_bindings import bind_item_posture_selection
from yoke_core.domain.item_posture_validation import ItemPostureError
from yoke_core.domain.qa_execution_environment_target import QaExecutionTargetError
from yoke_core.domain.qa_plan_attachments import attach_plan_to_item
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)


def bind_filed_item_posture(
    conn: Any,
    *,
    item_id: int,
    definition: Mapping[str, Any],
    posture: Mapping[str, Any],
    actor_id: Optional[int],
) -> Optional[dict[str, Any]]:
    """Bind a new item's posture and attach its plan in the caller's transaction.

    Returns the attachment, or ``None`` when no plan was selected.  A refused
    attach raises ``ItemPostureError`` naming the refusal and the way to file
    without a plan; the caller rolls the create back.
    """
    bind_item_posture_selection(
        conn,
        item_id=item_id,
        definition=definition,
        posture=posture,
        actor_id=actor_id,
        commit=False,
    )
    verification = posture.get("verification")
    if not isinstance(verification, Mapping) or verification.get("kind") != "plan":
        return None
    plan_id = int(verification["plan_id"])
    try:
        return attach_plan_to_item(
            conn,
            plan_id=plan_id,
            item_id=int(item_id),
            transition_id=ITEM_POSTURE_VERIFICATION_TRANSITION,
            qa_phase="verification",
            actor_id=actor_id,
            commit=False,
        )
    except (QaPlanError, QaExecutionTargetError) as exc:
        raise ItemPostureError(
            f"verification plan {plan_id} cannot be attached at "
            f"{ITEM_POSTURE_VERIFICATION_TRANSITION}: {exc}. Choose another "
            "plan with --verification-plan ID_OR_SLUG, or file without one "
            "using --verification-method none."
        ) from exc


__all__ = [
    "bind_filed_item_posture",
]
