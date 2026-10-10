"""Pure display text for an item's durable merge-queue handoff."""

from __future__ import annotations

from datetime import datetime

from yoke_contracts.timestamps import format_instant


def render_merge_queue_status(
    enqueued_at: datetime | str | None,
    landed_at: datetime | str | None,
    *,
    item_status: object = "",
) -> str:
    """Describe queue occupancy or landed work awaiting close-out."""
    if str(item_status or "") in {"done", "cancelled"}:
        return ""
    if enqueued_at in (None, ""):
        return ""
    enqueued = format_instant(enqueued_at)
    if landed_at not in (None, ""):
        return f"merge queue landed at {format_instant(landed_at)}; close-out pending"
    return f"in merge queue since {enqueued}"


__all__ = ["render_merge_queue_status"]
