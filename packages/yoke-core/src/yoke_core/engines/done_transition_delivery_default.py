"""Resolving and freezing a project's delivery default onto an empty item.

Split out of :mod:`done_transition_deploy_gates` to stay under the authored
file line budget; the two helpers here are used only by that module's
``_check_deployment_flow_guard``, at the release-stage support boundary.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.engines.done_transition_runtime import _query_item_field


def resolve_default_delivery_flow(*, item_project: str, workflow_id: str) -> str:
    """The project's workflow-specific or project-wide delivery default.

    Reuses the already-registered ``workflows.mechanics.get`` read (its
    ``delivery_defaults`` list already carries every project/workflow
    combination with an effective default) rather than adding a new function
    id for one more filtered read. A relay failure here raises, matching
    every other read in the deployment-flow guard: an unread authority is
    not the same fact as "nothing is configured", so it must not be reported
    with the same setup-guidance message.
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


def freeze_resolved_delivery_flow(item_id: int, flow_id: str, *, public_ref: str) -> str:
    """Write a resolved default onto the item exactly once, before it is used.

    Rereads the item's current ``deployment_flow`` immediately before
    writing and returns that value untouched when it is already non-empty,
    instead of overwriting it with the resolved default.

    No caller other than the one holding this item's live work claim can
    make that value non-empty out from under this reread at all:
    ``items.scalar.update`` (the only write path onto ``deployment_flow``)
    declares ``claim_required_kind="item"`` with no bypass for that kind
    (see ``yoke_function_dispatch_claims.py``), and ``work_claims`` carries
    a database-enforced unique index on the live claim per item
    (``idx_work_claims_active_item``, ``WHERE released_at IS NULL AND
    target_kind='item'``) — so at most one session ever holds this item's
    claim, and it is the same session running this done-transition. The
    reread exists to close a same-session, same-claim ordering gap
    instead: this session's own earlier read (in the done-transition
    runner, before this guard ran) can be stale by the time this freeze
    attempt executes, e.g. an operator set the field explicitly, through
    this same claimed session, in between. There is no cross-session race
    to exclude with a transaction or a new CAS field, because the claim
    system already excludes it structurally.

    Once a value lands, ``deployment_flow`` is non-empty and every later
    evaluation — including a later change to the project's default — takes
    the item-level value instead of resolving fresh, so a frozen item is
    never silently rerouted.
    """
    current = _query_item_field(item_id, "deployment_flow")
    if current:
        return current
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
    return flow_id


__all__ = ["freeze_resolved_delivery_flow", "resolve_default_delivery_flow"]
