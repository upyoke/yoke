"""Operator-facing summaries for Strategize carry-forward candidates."""

from __future__ import annotations

from typing import Any, Dict, List


def format_summary(
    candidate_set: Dict[str, Any],
    display_limit: int = 10,
) -> str:
    """Return an operator-facing summary for the State Refresh checkpoint.

    The backing candidate set is always complete (bounded by
    ``carry_limit``); ``display_limit`` only truncates what we print per
    bucket. This demotes LIMIT 10 / head -30 style caps to presentation-only
    behavior.
    """
    horizon = candidate_set["horizon_days"]
    carry_limit = candidate_set["carry_limit"]
    new_items = candidate_set["new"]
    carry_items = candidate_set["carry_forward"]
    reflected = candidate_set["reflected"]
    dismissed = candidate_set["dismissed"]
    truncated = candidate_set.get("truncated", False)

    lines: List[str] = []
    lines.append(
        f"### Landed-work carry-forward "
        f"(horizon: last {horizon}d, carry cap: {carry_limit})"
    )
    lines.append(
        f"- **Pending:** {len(new_items) + len(carry_items)} total "
        f"({len(new_items)} new this session, "
        f"{len(carry_items)} carry-forward)"
    )

    def _print_bucket(label: str, items: List[Dict[str, Any]]) -> None:
        if not items:
            return
        lines.append(f"  _{label}:_")
        for entry in items[:display_limit]:
            age = entry["age_days"]
            lines.append(
                f"  - {entry['yok_id']} ({entry['priority']}, "
                f"seen {age}d ago): {entry['title']}"
            )
        if len(items) > display_limit:
            lines.append(
                f"  - ... +{len(items) - display_limit} more "
                f"(display truncated; backing set complete)"
            )

    _print_bucket("new", new_items)
    _print_bucket("carry-forward", carry_items)

    if reflected:
        lines.append(f"- **Reflected:** {len(reflected)}")
    if dismissed:
        lines.append(f"- **Dismissed:** {len(dismissed)}")
    if truncated:
        lines.append(
            f"- **Note:** carry-limit cap ({carry_limit}) hit — "
            "raise `strategize_carry_limit` in machine config to surface more."
        )
    lines.append("")
    lines.append(
        "_Display truncated per bucket at "
        f"{display_limit} rows; backing candidate set remains complete within"
        " the bounded horizon._"
    )
    return "\n".join(lines)
