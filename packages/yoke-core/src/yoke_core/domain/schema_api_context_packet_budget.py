"""Read surface for the packet line budgets: budget, usage, headroom.

The budgets in :mod:`schema_api_context_seed` are enforced by the ``check``
verdict in :mod:`schema_api_context_cli` and by the packet-size tests, but
enforcement only speaks once a packet is already over. This module answers
the question before that: what does each role's packet spend today, and how
much room is left. Trimming a packet or raising a budget then starts from a
measured number instead of a failed gate.

:func:`packet_line_count` is the one counting rule; the gates in
:mod:`schema_api_context` call it too, so the reported usage is the same
number enforcement compares against.

Registered function id ``packets.budget.get``; CLI adapter
:data:`BUDGET_READ_COMMAND`.
"""

from __future__ import annotations

from typing import Any, Dict, List

from yoke_core.domain import schema_api_context_seed as seed


# The one command that answers "how much packet budget is left?". Named in
# every budget-exceeded message so the discovery path is a single command.
BUDGET_READ_COMMAND = "yoke packets budget get"


__all__ = [
    "BUDGET_READ_COMMAND",
    "packet_line_count",
    "packet_budget_report",
]


def packet_line_count(body: str) -> int:
    """Return the lines *body* spends against its packet budget."""
    return body.count("\n")


def packet_budget_report() -> Dict[str, Any]:
    """Return per-role and aggregate packet budget, usage, and headroom.

    Renders each role exactly once. Character counts are reported as usage
    only — the seed budgets are line-based, and no character limit is
    enforced anywhere.
    """
    from yoke_core.domain.schema_api_context import render_role_packet

    per_role_budget = seed.PACKET_LINE_BUDGET_PER_ROLE
    aggregate_budget = seed.PACKET_LINE_BUDGET_AGGREGATE
    roles: List[Dict[str, Any]] = []
    for role in sorted(seed.ROLE_TOPICS):
        body = render_role_packet(role)
        lines = packet_line_count(body)
        roles.append(
            {
                "role": role,
                "lines": lines,
                "budget": per_role_budget,
                "headroom": per_role_budget - lines,
                "characters": len(body),
                "over_budget": lines > per_role_budget,
            }
        )
    aggregate_lines = sum(row["lines"] for row in roles)
    return {
        "roles": roles,
        "per_role_budget": per_role_budget,
        "aggregate_budget": aggregate_budget,
        "aggregate_lines": aggregate_lines,
        "aggregate_characters": sum(row["characters"] for row in roles),
        "aggregate_headroom": aggregate_budget - aggregate_lines,
        "aggregate_over_budget": aggregate_lines > aggregate_budget,
    }
