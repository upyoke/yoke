"""Read surface for the packet budgets: budget, usage, and headroom.

The budgets in :mod:`schema_api_context_seed` are enforced by the ``check``
verdict in :mod:`schema_api_context_cli` and by the packet-size tests, but
enforcement only speaks once a packet is already over. This module answers
the question before that: what does each role's packet spend today, and how
much room is left. Trimming a packet or raising a budget then starts from a
measured number instead of a failed gate.

Two axes are budgeted, and the byte axis is the one that matters for
delivery. A line budget bounds nothing a harness truncates on: a packet can
sit under a 438-line cap while spending 107,818 bytes, because nothing stops
one line from carrying two thousand of them. Worse, a line-only cap rewards
exactly that shape — the observed root rules file reached 350 lines and
113,502 bytes with a single 6,981-byte line. Lines remain budgeted because
they keep a packet readable; bytes are budgeted because they decide whether
the packet arrives.

:func:`packet_line_count` and :func:`packet_byte_count` are the two counting
rules; the gates in :mod:`schema_api_context` call them too, so reported
usage is the same number enforcement compares against.

Registered function id ``packets.budget.get``; CLI adapter
:data:`BUDGET_READ_COMMAND`.
"""

from __future__ import annotations

from typing import Any, Dict, List

from yoke_contracts.startup_context_budget import estimated_tokens
from yoke_core.domain import schema_api_context_seed as seed


# The one command that answers "how much packet budget is left?". Named in
# every budget-exceeded message so the discovery path is a single command.
BUDGET_READ_COMMAND = "yoke packets budget get"


__all__ = [
    "BUDGET_READ_COMMAND",
    "check_aggregate_bytes",
    "check_aggregate_size",
    "check_role_packet_bytes",
    "check_role_packet_size",
    "packet_byte_count",
    "packet_line_count",
    "packet_budget_report",
]


def packet_line_count(body: str) -> int:
    """Return the lines *body* spends against its packet line budget."""
    return body.count("\n")


def packet_byte_count(body: str) -> int:
    """Return the UTF-8 bytes *body* spends against its packet byte budget.

    Bytes, not characters: every harness ceiling this feeds is measured in
    delivered bytes, and the hook composer that applies one encodes the body
    the same way before comparing.
    """
    return len(body.encode("utf-8"))


def _role_row(role: str, body: str) -> Dict[str, Any]:
    lines = packet_line_count(body)
    byte_count = packet_byte_count(body)
    return {
        "role": role,
        "lines": lines,
        "line_budget": seed.PACKET_LINE_BUDGET_PER_ROLE,
        "line_headroom": seed.PACKET_LINE_BUDGET_PER_ROLE - lines,
        "over_line_budget": lines > seed.PACKET_LINE_BUDGET_PER_ROLE,
        "bytes": byte_count,
        "byte_budget": seed.PACKET_BYTE_BUDGET_PER_ROLE,
        "byte_headroom": seed.PACKET_BYTE_BUDGET_PER_ROLE - byte_count,
        "over_byte_budget": byte_count > seed.PACKET_BYTE_BUDGET_PER_ROLE,
        "estimated_tokens": estimated_tokens(byte_count),
        "over_budget": (
            lines > seed.PACKET_LINE_BUDGET_PER_ROLE
            or byte_count > seed.PACKET_BYTE_BUDGET_PER_ROLE
        ),
    }


def packet_budget_report() -> Dict[str, Any]:
    """Return per-role and aggregate packet budget, usage, and headroom.

    Renders each role exactly once. Both axes carry a budget, a headroom and
    an over-budget flag, so a caller reading the report learns which axis is
    tight rather than only that something is.
    """
    from yoke_core.domain.schema_api_context import render_role_packet

    roles: List[Dict[str, Any]] = [
        _role_row(role, render_role_packet(role)) for role in sorted(seed.ROLE_TOPICS)
    ]
    aggregate_lines = sum(row["lines"] for row in roles)
    aggregate_bytes = sum(row["bytes"] for row in roles)
    return {
        "roles": roles,
        "per_role_line_budget": seed.PACKET_LINE_BUDGET_PER_ROLE,
        "per_role_byte_budget": seed.PACKET_BYTE_BUDGET_PER_ROLE,
        "aggregate_line_budget": seed.PACKET_LINE_BUDGET_AGGREGATE,
        "aggregate_byte_budget": seed.PACKET_BYTE_BUDGET_AGGREGATE,
        "aggregate_lines": aggregate_lines,
        "aggregate_bytes": aggregate_bytes,
        "aggregate_estimated_tokens": estimated_tokens(aggregate_bytes),
        "aggregate_line_headroom": seed.PACKET_LINE_BUDGET_AGGREGATE - aggregate_lines,
        "aggregate_byte_headroom": seed.PACKET_BYTE_BUDGET_AGGREGATE - aggregate_bytes,
        "aggregate_over_line_budget": (
            aggregate_lines > seed.PACKET_LINE_BUDGET_AGGREGATE
        ),
        "aggregate_over_byte_budget": (
            aggregate_bytes > seed.PACKET_BYTE_BUDGET_AGGREGATE
        ),
        "aggregate_over_budget": (
            aggregate_lines > seed.PACKET_LINE_BUDGET_AGGREGATE
            or aggregate_bytes > seed.PACKET_BYTE_BUDGET_AGGREGATE
        ),
    }


def check_role_packet_size(role: str) -> tuple[int, int]:
    """Return ``(line_count, budget)`` for the role's delivered packet."""
    from yoke_core.domain.schema_api_context import render_role_packet

    return (
        packet_line_count(render_role_packet(role)),
        seed.PACKET_LINE_BUDGET_PER_ROLE,
    )


def check_role_packet_bytes(role: str) -> tuple[int, int]:
    """Return ``(byte_count, budget)`` for the role's delivered packet.

    Bytes are measured on the compact body because that is the one that
    ships. The full body carries no budget: an agent reads it deliberately
    at the moment it applies, and capping it would cap teaching nobody is
    forced to carry.
    """
    from yoke_core.domain.schema_api_context import render_role_packet

    return (
        packet_byte_count(render_role_packet(role)),
        seed.PACKET_BYTE_BUDGET_PER_ROLE,
    )


def check_aggregate_size() -> tuple[int, int]:
    """Return ``(total_line_count, aggregate_budget)`` across all roles."""
    from yoke_core.domain.schema_api_context import render_role_packet

    total = sum(packet_line_count(render_role_packet(r)) for r in seed.ROLE_TOPICS)
    return (total, seed.PACKET_LINE_BUDGET_AGGREGATE)


def check_aggregate_bytes() -> tuple[int, int]:
    """Return ``(total_byte_count, aggregate_budget)`` across all roles."""
    from yoke_core.domain.schema_api_context import render_role_packet

    total = sum(packet_byte_count(render_role_packet(r)) for r in seed.ROLE_TOPICS)
    return (total, seed.PACKET_BYTE_BUDGET_AGGREGATE)
