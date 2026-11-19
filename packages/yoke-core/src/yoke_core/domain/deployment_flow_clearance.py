"""Whether an item's declared deployment flow discharges its delivery
obligation without a release wait -- the merge-only contract.

Shared by the done-transition engine's deployment-flow guard and redirect
and the standalone merge boundary's terminal transition, so every close-out
path reads the same answer from one project-scoped server read,
``done_transition.delivery_clearance``. The server resolves an empty flow to
the item's own project default, checks the flow is registered, and calls it
merge-only only when its own ``target_tier`` is null -- never from the flow
id's own spelling (an arbitrary or newly created flow must not waive a
release wait by name). When neither an explicit flow nor that default names
one, delivery is not required and the reading is merge-only. A flow-name
shortcut would still reproduce the documented deployment-guard defect of
returning clear for an unproven flow
(``docs/archive/decisions/gate-satisfier-ladders.md``).

The read is project-scoped (items.read on the item's project), so a project
operator without org admin can close out a merge; the org-admin
``workflows.mechanics.get`` and ``deployment_flows.get`` reads stay admin-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch
from yoke_core.domain.public_item_target import public_item_target

call_dispatcher = get_structured_dispatch().call_dispatcher

FUNCTION_ID = "done_transition.delivery_clearance"


@dataclass(frozen=True)
class DeliveryClearance:
    """Whether delivery is discharged without a release wait.

    ``blocked_reason`` is non-empty when an explicit or resolved flow is
    unregistered. An empty scalar with no configured default is merge-only:
    there is no required deployment to wait on.
    """

    merge_only: bool
    resolved_flow: str
    blocked_reason: str = ""


def resolve_delivery_clearance(
    *, public_ref: str, deploy_flow: str, workflow_id: str
) -> DeliveryClearance:
    """Resolve whether ``deploy_flow`` (or the item's project default, when
    empty) discharges delivery without a release wait.

    A refused or failed read raises: an unread authority is not the same
    fact as "nothing is configured", so it must not be reported as
    merge-only or with setup guidance.
    """
    if not public_ref:
        raise RuntimeError(
            f"{FUNCTION_ID} needs the item's public ref; the close-out read "
            "named none. Re-run the close-out with the item's PREFIX-N."
        )
    resp = call_dispatcher(
        function_id=FUNCTION_ID,
        target=public_item_target(public_ref),
        payload={"workflow_id": workflow_id, "deploy_flow": deploy_flow},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"{FUNCTION_ID} read failed: {message}")
    result = resp.result or {}
    if "merge_only" not in result:
        raise RuntimeError(f"{FUNCTION_ID} for {public_ref} named no 'merge_only' field")
    return DeliveryClearance(
        merge_only=bool(result["merge_only"]),
        resolved_flow=str(result.get("resolved_flow") or ""),
        blocked_reason=str(result.get("blocked_reason") or ""),
    )


def resolve_default_delivery_flow(*, public_ref: str, workflow_id: str) -> str:
    """The item's project default for its workflow, or ``""`` when none."""
    if not workflow_id:
        return ""
    return resolve_delivery_clearance(
        public_ref=public_ref, deploy_flow="", workflow_id=workflow_id
    ).resolved_flow


__all__ = [
    "DeliveryClearance",
    "FUNCTION_ID",
    "resolve_default_delivery_flow",
    "resolve_delivery_clearance",
]
