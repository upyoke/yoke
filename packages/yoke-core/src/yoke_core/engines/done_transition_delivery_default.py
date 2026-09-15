"""Freezing a project's resolved delivery default onto an empty item.

Split out of :mod:`done_transition_deploy_gates` to stay under the authored
file line budget; used only by that module's ``_check_deployment_flow_guard``,
at the release-stage support boundary. The resolution half of this boundary
now lives in :mod:`yoke_core.domain.deployment_flow_clearance`, shared with
the standalone merge boundary's own terminal transition; re-exported here so
existing callers of this module keep the same name.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.deployment_flow_clearance import (
    resolve_default_delivery_flow,
)


def freeze_resolved_delivery_flow(item_id: int, flow_id: str, *, public_ref: str) -> str:
    """Write a resolved default onto the item exactly once, before it is used.

    Calls ``items.deployment_flow.claim_default``, whose conditional
    ``UPDATE ... WHERE deployment_flow IS NULL OR deployment_flow=''``
    (checked by rowcount in the same transaction that reads it) is the
    actual exclusion boundary — not this call's own earlier empty read,
    which can go stale between that read and this write. An explicit
    operator reassignment of an already-set item keeps going through
    ``items.scalar.update`` unconditionally elsewhere; this path exists
    only to resolve an empty field, so it can never clobber one.

    Once a value lands, ``deployment_flow`` is non-empty and every later
    evaluation — including a later change to the project's default — takes
    the item-level value instead of resolving fresh, so a frozen item is
    never silently rerouted.
    """
    resp = call_dispatcher(
        function_id="items.deployment_flow.claim_default",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={"flow_id": flow_id},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(
            f"items.deployment_flow.claim_default failed: {message}"
        )
    result = resp.result or {}
    stored = str(result.get("deployment_flow") or "")
    if not stored:
        raise RuntimeError(
            "items.deployment_flow.claim_default reported success but named "
            f"no stored deployment_flow for {public_ref}"
        )
    if result.get("claimed"):
        print(
            f"Resolved and froze {public_ref}'s delivery flow to '{stored}' "
            "from the project's configured default."
        )
    return stored


__all__ = ["freeze_resolved_delivery_flow", "resolve_default_delivery_flow"]
