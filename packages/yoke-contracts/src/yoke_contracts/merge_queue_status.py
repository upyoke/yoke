"""Pure display text for an item's durable merge-queue handoff.

The label describes the landing in flight. For an item that already landed
that is its open re-land attempt, so every reader selects the label inputs
through the SQL below rather than the bare ``items`` columns: items alias
``i``, joined with :data:`LABEL_ATTEMPT_JOIN`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.timestamps import format_instant


LABEL_ATTEMPT_JOIN = (
    "LEFT JOIN merge_queue_landing_attempts mq_attempt "
    "ON mq_attempt.item_id = i.id AND mq_attempt.closed_at IS NULL"
)
LABEL_ENQUEUED_AT_SQL = (
    "CASE WHEN mq_attempt.item_id IS NULL THEN i.merge_queue_enqueued_at "
    "ELSE mq_attempt.enqueued_at END"
)
LABEL_LANDED_AT_SQL = (
    "CASE WHEN mq_attempt.item_id IS NULL THEN i.merge_queue_landed_at END"
)
#: One item's label inputs: ``status, enqueued_at, landed_at``.
LABEL_INPUTS_FOR_ITEM_SQL = (
    f"SELECT i.status, {LABEL_ENQUEUED_AT_SQL}, {LABEL_LANDED_AT_SQL} "
    f"FROM items i {LABEL_ATTEMPT_JOIN} WHERE i.id = %s"
)


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


def in_flight_landing(merge_queue: Mapping[str, Any] | None) -> dict[str, Any]:
    """The landing in flight from an item read's ``merge_queue`` block.

    That is the open re-land attempt when the block carries one, otherwise
    the current landing. A block from a server without attempts has no
    ``attempt`` key and reads as the current landing.
    """
    block = merge_queue or {}
    attempt = block.get("attempt") or {}
    source = attempt if attempt and attempt.get("closed_at") in (None, "") else block
    return {
        "pr_number": str(source.get("pr_number") or ""),
        "enqueued_at": source.get("enqueued_at"),
    }


__all__ = [
    "LABEL_ATTEMPT_JOIN",
    "LABEL_ENQUEUED_AT_SQL",
    "LABEL_INPUTS_FOR_ITEM_SQL",
    "LABEL_LANDED_AT_SQL",
    "in_flight_landing",
    "render_merge_queue_status",
]
