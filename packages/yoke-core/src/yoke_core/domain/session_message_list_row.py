"""The compact row a mailbox page serves instead of whole messages.

A mailbox page is read to decide which message to open. That decision
needs who sent it, where it stands, when it expires, and enough of the
first line to recognize it — not the body, and not one record per
recipient per message. Serving the whole thing made a forty-row page cost
tens of kilobytes of a reader's context, nearly all of it prose the reader
was scrolling past.

So the page's default is this projection, and the picked message is read
whole with ``yoke messages get MESSAGE-ID``. Callers that genuinely render
every body from the page — the Messages view — ask for ``detail="full"``
and receive the unprojected summaries.

This is a projection of an already-built summary, never a second thinner
query: visibility is decided from the same recipient rows this drops, so
they are read either way.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.read_detail import excerpt

#: Fields copied straight through when the summary carries them.
_CARRIED = (
    "sender_actor_label",
    "sender_session_id",
    "sender_surface_label",
    "created_at",
    "expires_at",
    "cancelled_at",
    "cancellation_reason",
    "needs_attention",
    "acknowledgement_command",
)


def recipient_rows(message: dict[str, Any]) -> list[Any]:
    """Every recipient record on a full message: sessions, people, the seat."""
    steering = message.get("steering_recipient")
    return [
        *(message.get("recipients") or []),
        *(message.get("actor_recipients") or []),
        *([steering] if steering else []),
    ]


def message_list_row(summary: dict[str, Any]) -> dict[str, Any]:
    """Project one message summary down to its mailbox list row."""
    message_id = summary["message_id"]
    rows = recipient_rows(summary)
    row: dict[str, Any] = {
        "message_id": message_id,
        # One "from", already resolved: a message sent by a session names
        # that session, and one sent by a person names the person.
        "sender": (
            summary.get("sender_session_id") or summary.get("sender_actor_label")
        ),
        "recipient_count": len(rows),
        "recipient_states": sorted(
            {str(record.get("state") or record.get("liveness") or "") for record in rows}
        ),
        "body_excerpt": excerpt(summary.get("body")),
        "body_read": f"yoke messages get {message_id}",
    }
    row.update(
        {key: summary[key] for key in _CARRIED if key in summary},
    )
    steering = summary.get("steering_recipient")
    if isinstance(steering, dict):
        row["steering_summary"] = str(steering.get("summary") or "")
    return row


__all__ = ["message_list_row", "recipient_rows"]
