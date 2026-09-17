"""Whether an item's declared deployment flow discharges its delivery
obligation without a release wait -- the merge-only contract.

Shared by the done-transition engine's post-merge deployment-flow guard and
the standalone merge boundary's terminal transition, so the two close-out
paths read the same registered flow, the same target tier, and the same
project delivery default rather than each guessing from the flow id's own
name. A flow is merge-only only when it is genuinely registered AND its own
``target_tier`` resolves to null -- never from the flow id's own spelling
(an arbitrary or newly created flow must not waive a release wait by name).
An empty scalar still resolves the project's configured default first. When
neither an explicit flow nor that default names one, delivery is not required
and the reading is merge-only, matching a release wait that already says an
item with no deployment posture or flow passes through. A flow-name
shortcut would still reproduce the documented deployment-guard defect of
returning clear for an unproven flow
(``docs/archive/decisions/gate-satisfier-ladders.md``).
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
    marker -- an explicit ``"value": null`` in the response. Raises on an
    unread flow, and on a response that omits the ``value`` field entirely
    rather than naming it null: a malformed response is not the same fact
    as a flow that was read and resolved empty."""
    resp = call_dispatcher(
        function_id="deployment_flows.get",
        target=TargetRef(kind="global"),
        payload={"flow_id": deploy_flow, "field": "target_tier"},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"deployment_flows.get read failed: {message}")
    result = resp.result or {}
    if "value" not in result:
        raise RuntimeError(
            f"deployment_flows.get for {deploy_flow!r} named no 'value' field"
        )
    value = result["value"]
    return "" if value is None else str(value)


@dataclass(frozen=True)
class DeliveryClearance:
    """Whether delivery is discharged without a release wait.

    ``blocked_reason`` is non-empty when an explicit or resolved flow is
    unreadable or unregistered. An empty scalar with no configured
    default is merge-only: there is no required deployment to wait on.
    """

    merge_only: bool
    resolved_flow: str
    blocked_reason: str = ""


def resolve_delivery_clearance(
    *, deploy_flow: str, item_project: str, workflow_id: str
) -> DeliveryClearance:
    """Resolve whether ``deploy_flow`` (or the project's configured default,
    when empty) discharges delivery without a release wait.

    An empty ``deployment_flow`` scalar resolves the project's configured
    default first, exactly as the done-transition engine's own guard does,
    so a newly supported item with a real default still waits on it.
    When that default is also empty, delivery is not required and the
    close-out is merge-only rather than a setup refusal.
    """
    flow = deploy_flow
    if not flow:
        flow = resolve_default_delivery_flow(
            item_project=item_project, workflow_id=workflow_id
        )
        if not flow:
            return DeliveryClearance(merge_only=True, resolved_flow="")
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
