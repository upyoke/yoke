"""Resolving and freezing a project's delivery default onto an empty item.

Split out of :mod:`done_transition_deploy_gates` to stay under the authored
file line budget; the two helpers here are used only by that module's
``_check_deployment_flow_guard``, at the release-stage support boundary.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


def resolve_default_delivery_flow(*, item_project: str, workflow_id: str) -> str:
    """The project's workflow-specific or project-wide delivery default.

    Reuses the already-registered ``workflows.mechanics.get`` read (its
    ``delivery_defaults`` list already carries every project/workflow
    combination with an effective default) rather than adding a new function
    id for one more filtered read. A relay failure here is not fatal to the
    transition — it just forfeits the opportunistic resolution, leaving the
    caller to report the same "nothing resolved" outcome it would otherwise.
    """
    if not workflow_id:
        return ""
    resp = call_dispatcher(
        function_id="workflows.mechanics.get",
        target=TargetRef(kind="global"),
        payload={},
    )
    if not resp.success:
        return ""
    for entry in (resp.result or {}).get("delivery_defaults") or []:
        if (
            str(entry.get("project") or "") == item_project
            and str(entry.get("workflow_id") or "") == workflow_id
        ):
            return str(entry.get("flow_id") or "")
    return ""


def freeze_resolved_delivery_flow(item_id: int, flow_id: str, *, public_ref: str) -> None:
    """Write a resolved default onto the item exactly once, before it is used.

    Once this lands, ``deployment_flow`` is non-empty and every later
    evaluation — including a later change to the project's default — takes
    the item-level value instead of resolving fresh, so a frozen item is
    never silently rerouted.
    """
    resp = call_dispatcher(
        function_id="items.scalar.update",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={"field": "deployment_flow", "value": flow_id},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"items.scalar.update(deployment_flow) failed: {message}")
    print(
        f"Resolved and froze {public_ref}'s delivery flow to '{flow_id}' from "
        "the project's configured default."
    )


__all__ = ["freeze_resolved_delivery_flow", "resolve_default_delivery_flow"]
