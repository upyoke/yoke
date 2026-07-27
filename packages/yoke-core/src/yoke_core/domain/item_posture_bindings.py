"""Create-time bindings for definition-bounded item posture.

The item row keeps the selected posture as the durable declaration.  This
module binds selections that already have enough information at filing time
to their shared runtime records.  Ad-hoc verification intentionally remains a
method selection until the executing harness authors the concrete case
contract from the instruction and actual target.
"""

from __future__ import annotations

from typing import Any, Mapping


ITEM_POSTURE_VERIFICATION_TRANSITION = "reviewing-implementation"


def bind_item_posture_on_create(
    conn: Any,
    *,
    item_id: int,
    definition: Mapping[str, Any],
    posture: Mapping[str, Any],
    actor_id: int,
    commit: bool = True,
) -> dict[str, Any]:
    """Bind filing-time posture selections to shared runtime authorities."""
    verification = posture.get("verification")
    if not isinstance(verification, Mapping):
        if commit:
            conn.commit()
        return {"verification": None}

    stage_ids = {
        str(stage.get("id"))
        for stage in definition.get("stages", ())
        if isinstance(stage, Mapping)
    }
    if ITEM_POSTURE_VERIFICATION_TRANSITION not in stage_ids:
        raise ValueError(
            "verification posture requires a reviewing-implementation stage"
        )

    kind = str(verification.get("kind") or "")
    if kind == "plan":
        from yoke_core.domain.qa_plan_attachments import attach_plan_to_item

        attachment = attach_plan_to_item(
            conn,
            plan_id=int(verification["plan_id"]),
            item_id=int(item_id),
            transition_id=ITEM_POSTURE_VERIFICATION_TRANSITION,
            actor_id=int(actor_id),
            commit=False,
        )
        if commit:
            conn.commit()
        return {"verification": {"kind": "plan", "attachment": attachment}}

    if kind == "ad_hoc":
        if commit:
            conn.commit()
        return {
            "verification": {
                "kind": "ad_hoc",
                "method_id": str(verification["method_id"]),
                "transition_id": ITEM_POSTURE_VERIFICATION_TRANSITION,
            },
        }

    raise ValueError(f"unsupported verification posture kind {kind!r}")


__all__ = [
    "ITEM_POSTURE_VERIFICATION_TRANSITION",
    "bind_item_posture_on_create",
]
