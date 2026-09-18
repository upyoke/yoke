"""Reading the shared delivery ladder, and refusing on what it says.

The verdict itself is :mod:`yoke_core.domain.delivery_evidence_ladder`,
resolved server-side because its containment rung needs a connection and a
repository comparison source. What lives here is the engine's half: the
relay read, and the two refusals whose narratives the deployment guard would
otherwise have to carry inline.

Both refusals exist because of the same mistake in opposite directions. An
unreadable delivery answer is not a negative one, so it must not be reported
as "never deployed"; and a delivery the selected flow demonstrably made is
not out-of-band, so it must not be recorded as though it were.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_contracts.api.function_call import TargetRef


def _parent():
    from yoke_core.engines import done_transition as _dt

    return _dt


DISCHARGED = "discharged"
UNDETERMINED = "undetermined"


def read_delivery_evidence(relay_read: Any, item_id: int) -> Dict[str, Any]:
    """The shared delivery ladder's verdict for this item."""
    return relay_read(
        "done_transition.delivery_evidence",
        TargetRef(kind="item", item_id=int(item_id)),
    )


def undetermined_refusal(
    delivery: Dict[str, Any],
    *,
    public_ref: str,
    old_status: str,
) -> Optional[Tuple[int, str]]:
    """Refuse a delivery question that could not be answered at all.

    Reported as unreadable rather than negative on purpose. Telling an owner
    their item was never delivered — when the truth is that the comparison
    source was unwell — sends them to redeploy, and redeploying to make one
    merge the candidate tip makes every other member of that release fail
    the same way.
    """
    print("\n=== Deployment evidence guard ===")
    print(
        f"Blocked: whether {public_ref} has been delivered could not be "
        f"determined: {delivery.get('reason') or 'no reason reported'}."
    )
    print(
        "\nThis is an unreadable answer, not a negative one — the item may "
        "well be delivered already."
    )
    recovery = str(delivery.get("recovery") or "")
    if recovery:
        print(f"\n{recovery}")
    print(
        "Do not redeploy to force a verdict; the other members of that "
        "release would then fail the same way."
    )
    return 7, old_status


def false_out_of_band_refusal(
    *,
    public_ref: str,
    deploy_flow: str,
    run_id: str,
    old_status: str,
) -> Optional[Tuple[int, str]]:
    """Refuse ``--skip-deploy`` for a delivery the selected flow made.

    The flag's whole meaning is "this was delivered outside the flow". Using
    it on an item the flow delivered writes a false record of how the
    release happened, and it was reached for only because the ordinary
    close-out was refusing — which is the defect, not the reason.
    """
    print("\n=== Deployment evidence guard ===")
    print(
        f"Blocked: --skip-deploy passed for {public_ref}, but its selected "
        f"flow '{deploy_flow}' already delivered it (run {run_id})."
    )
    print(
        "\n--skip-deploy records delivery as out-of-band. Recording a "
        "selected-flow delivery that way would be a false record."
    )
    print("Close this item out without --skip-deploy.")
    return 7, old_status


def redirect_to_delivery_stage(
    item_id: int,
    old_status: str,
    delivery_stage_id: str | None,
    *,
    public_ref: str,
) -> Tuple[int, str]:
    """Move to the pinned definition's delivery stage when it declares one.

    ``public_ref`` is the caller's already-resolved public ref, so the redirect
    narrative renders without opening a local connection.
    """
    if delivery_stage_id is None:
        return 7, old_status
    print(f"Merge completed successfully. Setting status to '{delivery_stage_id}'.")
    _parent()._update_item_direct(
        item_id,
        "status",
        delivery_stage_id,
        env_overrides={"YOKE_STATUS_SOURCE": "done-transition"},
        public_ref=public_ref,
    )
    print(
        f"\nNext step: run '/yoke usher {public_ref}' to execute "
        "the deployment pipeline."
    )
    return 7, delivery_stage_id


__all__ = [
    "DISCHARGED",
    "UNDETERMINED",
    "false_out_of_band_refusal",
    "read_delivery_evidence",
    "redirect_to_delivery_stage",
    "undetermined_refusal",
]
