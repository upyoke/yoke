"""Sender projection shared by leased and read-only hook messages."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_message_reads import sender_identity_projection


def delivery_message_projection(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Return the authenticated message fields exposed to hook rendering."""
    message = {
        "message_id": str(row["message_id"]),
        "body": str(row["body"]),
        "sender_actor_id": int(row["sender_actor_id"]),
        "sender_session_id": row.get("sender_session_id"),
        "sender_surface": row.get("sender_surface"),
    }
    message.update(
        sender_identity_projection(
            conn,
            int(row["sender_actor_id"]),
            sender_surface=row.get("sender_surface"),
        )
    )
    return message


__all__ = ["delivery_message_projection"]
