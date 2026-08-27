"""Pure display text for an item's durable merge-queue handoff."""

from __future__ import annotations


def render_merge_queue_status(
    enqueued_at: object,
    landed_at: object,
    *,
    item_status: object = "",
) -> str:
    """Describe queue occupancy or landed work awaiting close-out."""
    if str(item_status or "") in {"done", "cancelled"}:
        return ""
    enqueued = str(enqueued_at or "").strip()
    if not enqueued:
        return ""
    landed = str(landed_at or "").strip()
    if landed:
        return f"merge queue landed at {landed}; close-out pending"
    return f"in merge queue since {enqueued}"


__all__ = ["render_merge_queue_status"]
