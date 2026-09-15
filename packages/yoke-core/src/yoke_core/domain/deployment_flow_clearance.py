"""Whether an item's declared deployment flow discharges its delivery
obligation without a release wait -- the merge-only contract.

Shared by the done-transition engine's post-merge deployment-flow guard and
the standalone merge boundary's terminal transition, so the two close-out
paths read the same registered flow, the same target tier, and the same
project delivery default rather than each guessing from the flow id's own
name. A flow is merge-only only when either its id ends ``-internal`` (the
existing naming convention for flows with no registration to look up) or a
genuinely registered flow's own ``target_tier`` resolves to null -- never
from an empty ``deployment_flow`` scalar alone, which instead falls back to
the project's configured default before any merge-only judgment is made.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


def resolve_default_delivery_flow(*, item_project: str, workflow_id: str) -> str:
    """The project's workflow-specific or project-wide delivery default.

    Reuses the already-registered ``workflows.mechanics.get`` read (its
    ``delivery_defaults`` list already carries every project/workflow
    combination with an effective default) rather than adding a new function
    id for one more filtered read. A relay failure here raises, matching
    every other read in this module: an unread authority is not the same
    fact as "nothing is configured", so it must not be reported with the
    same setup-guidance message.
    """
    if not workflow_id:
        return ""
    resp = call_dispatcher(
        function_id="workflows.mechanics.get",
        target=TargetRef(kind="global"),
        payload={},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"workflows.mechanics.get read failed: {message}")
    for entry in (resp.result or {}).get("delivery_defaults") or []:
        if (
            str(entry.get("project") or "") == item_project
            and str(entry.get("workflow_id") or "") == workflow_id
        ):
            return str(entry.get("flow_id") or "")
    return ""


def registered_deployment_flow_ids() -> list[str]:
    """Every deployment flow id currently registered."""
    resp = call_dispatcher(
        function_id="done_transition.registered_flow_ids",
        target=TargetRef(kind="global"),
        payload={},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"done_transition.registered_flow_ids read failed: {message}")
    return list((resp.result or {}).get("flow_ids") or [])


def deployment_flow_target_tier(deploy_flow: str) -> str:
    """One registered flow's semantic target tier; ``""`` is the merge-only
    marker. Raises on an unread flow, matching every other read here: an
    unread authority is not the same fact as a flow that resolved empty."""
    resp = call_dispatcher(
        function_id="deployment_flows.get",
        target=TargetRef(kind="global"),
        payload={"flow_id": deploy_flow, "field": "target_tier"},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"deployment_flows.get read failed: {message}")
    value = (resp.result or {}).get("value")
    return "" if value is None else str(value)


@dataclass(frozen=True)
class DeliveryClearance:
    """Whether delivery is discharged without a release wait.

    ``blocked_reason`` is non-empty when neither an explicit flow nor a
    configured default names one at all -- there is no clearance question
    to answer yet, so the caller refuses rather than guessing either way.
    """

    merge_only: bool
    resolved_flow: str
    blocked_reason: str = ""


def resolve_delivery_clearance(
    *, deploy_flow: str, item_project: str, workflow_id: str
) -> DeliveryClearance:
    """Resolve whether ``deploy_flow`` (or the project's configured default,
    when empty) discharges delivery without a release wait.

    An empty ``deployment_flow`` scalar is never itself the merge-only
    signal -- it resolves the project's configured default first, exactly
    as the done-transition engine's own guard does, so a newly supported
    item with a real default configured still waits on it.
    """
    flow = deploy_flow
    if not flow:
        flow = resolve_default_delivery_flow(
            item_project=item_project, workflow_id=workflow_id
        )
        if not flow:
            return DeliveryClearance(
                merge_only=False,
                resolved_flow="",
                blocked_reason=(
                    f"no deployment flow selected, and project {item_project!r} "
                    "has no workflow-specific or project-wide delivery default "
                    f"configured for workflow {workflow_id!r}."
                ),
            )
    if flow.endswith("-internal"):
        return DeliveryClearance(merge_only=True, resolved_flow=flow)
    if flow not in registered_deployment_flow_ids():
        return DeliveryClearance(
            merge_only=False,
            resolved_flow=flow,
            blocked_reason=f"deployment_flow {flow!r} is not a registered deployment flow.",
        )
    return DeliveryClearance(
        merge_only=deployment_flow_target_tier(flow) == "", resolved_flow=flow,
    )


__all__ = [
    "DeliveryClearance",
    "deployment_flow_target_tier",
    "registered_deployment_flow_ids",
    "resolve_default_delivery_flow",
    "resolve_delivery_clearance",
]
