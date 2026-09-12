"""One rendering of session consumption, shared by every surface.

The board, the session roster, and the workbench all answer the same two
questions — how many tokens, and what would they have cost — so they
answer them with the same words. A figure that reads ``1.2m`` on the
board and ``1,234,567`` in the roster invites the reader to wonder
whether they are the same measurement.

Every rendering here is honest about what it does not know. An unread
session shows nothing rather than a zero; a partial reading is marked;
and a cost that could not be priced shows why rather than a dash that
could equally mean "free". The dollar figure always reads as an estimate
of API-equivalent spend, never as plan consumption.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.session_usage_cost import COST_COMPLETE, SessionCost
from yoke_contracts.session_usage_facts import USAGE_COMPLETE, SessionUsage


#: Marks a figure computed from an incomplete reading. Placed after the
#: value so a column of numbers still lines up on the digits.
PARTIAL_MARK = "~"

#: What a session with no reading at all shows.
UNREAD_DISPLAY = "—"


def compact_tokens(count: int) -> str:
    """Render a token count at the scale an operator reads it in."""
    if count <= 0:
        return "0"
    if count >= 1_000_000:
        scaled, suffix = count / 1_000_000, "m"
    elif count >= 1_000:
        scaled, suffix = count / 1_000, "k"
    else:
        return str(count)
    precision = 1 if scaled < 10 else 0
    return f"{scaled:.{precision}f}".rstrip("0").rstrip(".") + suffix


def compact_usd(amount: float) -> str:
    """Render an estimate at a precision the estimate actually supports."""
    if amount <= 0:
        return "$0"
    if amount < 1:
        return f"${amount:.2f}"
    if amount < 100:
        return f"${amount:.2f}".rstrip("0").rstrip(".")
    return f"${amount:,.0f}"


def tokens_display(usage: Optional[SessionUsage]) -> str:
    """Render one session's token total, marked when partly unknown."""
    if usage is None or not usage.models:
        return UNREAD_DISPLAY
    total = usage.billable_tokens()
    if total <= 0:
        return UNREAD_DISPLAY
    mark = "" if usage.status == USAGE_COMPLETE else PARTIAL_MARK
    return f"{compact_tokens(total)}{mark}"


def cost_display(cost: Optional[SessionCost]) -> str:
    """Render one session's estimate, marked when partly unpriced."""
    if cost is None or not cost.priced():
        return UNREAD_DISPLAY
    mark = "" if cost.status == COST_COMPLETE else PARTIAL_MARK
    return f"{compact_usd(cost.usd)}{mark}"


def usage_cell(usage: Optional[SessionUsage], cost: Optional[SessionCost]) -> str:
    """Render both figures as one compact cell for a table."""
    tokens = tokens_display(usage)
    money = cost_display(cost)
    if tokens == UNREAD_DISPLAY and money == UNREAD_DISPLAY:
        return UNREAD_DISPLAY
    return f"{tokens} · {money}"


def usage_title(usage: Optional[SessionUsage], cost: Optional[SessionCost]) -> str:
    """The full explanation behind a compact cell, for a tooltip or note.

    Everything a compact figure had to drop lives here: which reading was
    partial and why, where the prices came from and when they were
    checked, and the standing caveat that this is API-equivalent spend
    rather than consumption of any subscription plan.
    """
    parts: list[str] = []
    if usage is None or not usage.models:
        parts.append("no consumption recorded for this session yet")
    else:
        parts.append(f"{usage.billable_tokens():,} tokens recorded")
        if usage.source:
            parts.append(f"read from {usage.source}")
        if usage.status != USAGE_COMPLETE and usage.reason:
            parts.append(f"partial: {usage.reason}")
        if usage.cost_caveat:
            parts.append(f"tokens exact, pricing uncertain: {usage.cost_caveat}")
    if cost is not None and cost.priced():
        parts.append("estimated API-equivalent cost, not plan consumption")
        if cost.price_basis:
            parts.append(f"prices from {cost.price_basis}")
        if cost.effective_date:
            parts.append(f"effective {cost.effective_date}")
        if cost.checked_date:
            parts.append(f"checked {cost.checked_date}")
        if cost.status != COST_COMPLETE and cost.reason:
            parts.append(f"partial: {cost.reason}")
    elif cost is not None and cost.reason:
        parts.append(f"no cost estimate: {cost.reason}")
    return " · ".join(parts)


def usage_projection(usage_totals: object) -> dict[str, object]:
    """Render-ready consumption facts for one stored reading.

    Surfaces receive derived values rather than the stored document, so
    the pricing rules live in one place and a table, a card, and a summed
    tile cannot disagree about what a session cost. ``None`` in either
    figure means "not measured" and is what a caller must not render as a
    zero; ``note`` always explains whatever the compact figures dropped.
    """
    from yoke_contracts.session_usage_facts import usage_from_document
    from yoke_contracts.session_usage_pricing import estimated_session_cost

    usage = usage_from_document(usage_totals)
    cost = estimated_session_cost(usage)
    measured = usage is not None and usage.billable_tokens() > 0
    return {
        "usage_tokens": usage.billable_tokens() if measured else None,
        "usage_status": usage.status if usage is not None else None,
        "usage_cost_usd": cost.usd if cost.priced() else None,
        "usage_cost_status": cost.status,
        "usage_note": usage_title(usage, cost),
    }


#: The keys :func:`usage_projection` returns, for read-model field lists.
USAGE_PROJECTION_FIELDS = (
    "usage_tokens",
    "usage_status",
    "usage_cost_usd",
    "usage_cost_status",
    "usage_note",
)


__all__ = [
    "PARTIAL_MARK",
    "USAGE_PROJECTION_FIELDS",
    "UNREAD_DISPLAY",
    "compact_tokens",
    "compact_usd",
    "cost_display",
    "tokens_display",
    "usage_cell",
    "usage_projection",
    "usage_title",
]
