"""Packet budget read handler.

Function id registered here:

- ``packets.budget.get`` — returns each packet role's configured line and
  byte budgets, its current rendered usage on both axes, and the remaining
  headroom on each, plus the same figures for the aggregate corpus.
  Read-only; renders the packets it measures, so it runs client-local like
  its ``packets.render`` / ``packets.check`` siblings.

Sibling of :mod:`orchestration`, which hosts the rest of the packet family
and is at the authored-file line cap.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class PacketsBudgetGetRequest(BaseModel):
    pass


class PacketsBudgetGetResponse(BaseModel):
    roles: List[Dict[str, Any]]
    per_role_line_budget: int
    per_role_byte_budget: int
    aggregate_line_budget: int
    aggregate_byte_budget: int
    aggregate_lines: int
    aggregate_bytes: int
    aggregate_estimated_tokens: int
    aggregate_line_headroom: int
    aggregate_byte_headroom: int
    aggregate_over_line_budget: bool
    aggregate_over_byte_budget: bool
    aggregate_over_budget: bool


def handle_packets_budget_get(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.schema_api_context_packet_budget import (
        packet_budget_report,
    )

    try:
        report = packet_budget_report()
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="downstream_failure",
                message=f"packet budget report failed: {exc}",
            ),
        )
    return HandlerOutcome(result_payload=report, primary_success=True)


__all__ = [
    "PacketsBudgetGetRequest",
    "PacketsBudgetGetResponse",
    "handle_packets_budget_get",
]
