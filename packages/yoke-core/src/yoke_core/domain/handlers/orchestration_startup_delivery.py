"""Startup-delivery budget read handler.

Function id registered here:

- ``packets.startup_delivery.get`` — returns, per harness, the combined
  instruction payload each startup channel delivers, its budget, its
  headroom, and the contributing files. Answers the question the per-packet
  budgets cannot: whether the text a surface is actually handed fits the
  channel carrying it. Read-only; measures the checkout named by
  ``target_root``, so it runs client-local like its ``packets.render`` /
  ``packets.budget.get`` siblings.

Sibling of :mod:`orchestration`, which hosts the rest of the packet family
and is at the authored-file line cap.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class PacketsStartupDeliveryGetRequest(BaseModel):
    target_root: Optional[str] = None


class PacketsStartupDeliveryGetResponse(BaseModel):
    target_root: str
    channels: List[Dict[str, Any]]
    over_budget: List[str]


def handle_packets_startup_delivery_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain.startup_delivery_budget import startup_delivery_report

    from yoke_core.domain.handlers.orchestration_agents import resolve_target_root

    payload = request.payload or {}
    try:
        target_root = resolve_target_root(payload.get("target_root"))
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=(
                    "this checkout could not be resolved from the current "
                    f"directory ({exc}); pass --target-root PATH naming the "
                    "checkout whose startup payload should be measured"
                ),
                jsonpath="$.payload.target_root",
            ),
        )
    try:
        report = startup_delivery_report(target_root)
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="downstream_failure",
                message=f"startup delivery report failed: {exc}",
            ),
        )
    return HandlerOutcome(result_payload=report, primary_success=True)


__all__ = [
    "PacketsStartupDeliveryGetRequest",
    "PacketsStartupDeliveryGetResponse",
    "handle_packets_startup_delivery_get",
]
