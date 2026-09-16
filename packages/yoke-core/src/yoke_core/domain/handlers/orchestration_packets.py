"""Packet render and check handlers.

Function ids registered here:

- ``packets.render.run`` — render one role's packet, or one topic within it,
  at the compact depth that ships or the full depth an agent reads on demand.
- ``packets.check.run`` — the packet gate. Reports seed/live drift, both
  budgeted packet axes, and every harness startup channel whose delivered
  payload exceeds the channel carrying it.

Sibling of :mod:`orchestration`, which hosts the board reads and is at the
authored-file line cap.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class PacketsRenderRequest(BaseModel):
    role: str
    topic: Optional[str] = None
    detail: Optional[str] = None


class PacketsRenderResponse(BaseModel):
    role: str
    topic: Optional[str]
    detail: str
    body: str
    byte_count: int


def handle_packets_render(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.schema_api_context import (
        render_role_packet,
        render_topic_packet,
    )
    from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_COMPACT

    payload = request.payload or {}
    role = payload.get("role")
    if not isinstance(role, str) or not role:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid", message="role is required",
                jsonpath="$.payload.role",
            ),
        )
    topic = payload.get("topic") or None
    detail = payload.get("detail") or PACKET_DETAIL_COMPACT
    try:
        body = (
            render_topic_packet(topic, role=role, detail=detail)
            if topic
            else render_role_packet(role, detail=detail)
        )
    except KeyError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="not_found",
                message=f"unknown packet role {role!r}: {exc}",
                jsonpath="$.payload.role",
            ),
        )
    except ValueError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid", message=str(exc), jsonpath="$.payload",
            ),
        )
    return HandlerOutcome(
        result_payload={
            "role": role,
            "topic": topic,
            "detail": detail,
            "body": body,
            "byte_count": len(body.encode("utf-8")),
        },
        primary_success=True,
    )


class PacketsCheckRequest(BaseModel):
    target_root: Optional[str] = None


class PacketsCheckResponse(BaseModel):
    drift: List[str]
    seed_ok: bool
    packet_budget: Dict[str, Any]
    startup_delivery: Dict[str, Any]
    over_budget: List[str]
    ok: bool


def handle_packets_check(request: FunctionCallRequest) -> HandlerOutcome:
    """Report drift, both packet budget axes, and per-channel delivery.

    Drift alone used to be the whole verdict, which let a packet pass its
    check while spending thirteen times the bytes its delivery channel
    accepts. The budget and delivery figures travel with the drift list so
    one call answers whether the packets are correct *and* whether they
    arrive.
    """
    from yoke_contracts.startup_context_budget import budget_phrase
    from yoke_core.domain.handlers.orchestration_agents import resolve_target_root
    from yoke_core.domain.schema_api_context import detect_seed_drift
    from yoke_core.domain.schema_api_context_packet_budget import (
        BUDGET_READ_COMMAND,
        packet_budget_report,
    )
    from yoke_core.domain.startup_delivery_budget import (
        DELIVERY_READ_COMMAND,
        startup_delivery_report,
    )

    payload = request.payload or {}
    try:
        budget = packet_budget_report()
        delivery = startup_delivery_report(
            resolve_target_root(payload.get("target_root"))
        )
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="downstream_failure",
                message=f"packet check could not measure the packets: {exc}",
            ),
        )
    drift = list(detect_seed_drift())
    over: List[str] = []
    for row in budget["roles"]:
        if row["over_line_budget"]:
            over.append(
                f"role={row['role']} packet has {row['lines']} lines "
                f"(budget {row['line_budget']}); read "
                f"`{BUDGET_READ_COMMAND}`"
            )
        if row["over_byte_budget"]:
            over.append(
                f"role={row['role']} packet spends "
                f"{budget_phrase(row['bytes'], row['byte_budget'])}; read "
                f"`{BUDGET_READ_COMMAND}`"
            )
    if budget["aggregate_over_line_budget"]:
        over.append(
            f"aggregate packets total {budget['aggregate_lines']} lines "
            f"(budget {budget['aggregate_line_budget']}); read "
            f"`{BUDGET_READ_COMMAND}`"
        )
    if budget["aggregate_over_byte_budget"]:
        over.append(
            "aggregate packets spend "
            + budget_phrase(
                budget["aggregate_bytes"], budget["aggregate_byte_budget"]
            )
            + f"; read `{BUDGET_READ_COMMAND}`"
        )
    over.extend(
        f"{line}; read `{DELIVERY_READ_COMMAND}`"
        for line in delivery["over_budget"]
    )
    return HandlerOutcome(
        result_payload={
            "drift": drift,
            "seed_ok": not drift,
            "packet_budget": budget,
            "startup_delivery": delivery,
            "over_budget": over,
            "ok": not drift and not over,
        },
        primary_success=True,
    )


__all__ = [
    "PacketsCheckRequest",
    "PacketsCheckResponse",
    "PacketsRenderRequest",
    "PacketsRenderResponse",
    "handle_packets_check",
    "handle_packets_render",
]
