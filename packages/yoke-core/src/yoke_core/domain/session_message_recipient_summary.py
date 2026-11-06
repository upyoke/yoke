"""Count distinct message parties while retaining all delivery records."""

from __future__ import annotations

from collections import Counter
from typing import Any


def recipient_rows(message: dict[str, Any]) -> list[dict[str, Any]]:
    """The seat and its matching session receipt represent one party."""
    sessions = message.get("recipients") or []
    rows = [*sessions, *(message.get("actor_recipients") or [])]
    steering = message.get("steering_recipient")
    session_ids = {row.get("session_id") for row in sessions if row.get("session_id")}
    if steering and steering.get("session_id") not in session_ids:
        rows.append(steering)
    return rows


def recipient_summary(message: dict[str, Any]) -> dict[str, Any]:
    """Counts and states shared by full reads, list rows, previews and sends."""
    rows = recipient_rows(message)
    counts = Counter(str(row.get("state") or "pending") for row in rows)
    # A queued launch is addressed before a session receipt can exist.
    if not rows and message.get("recipient_count"):
        counts[str(message.get("state") or "pending")] = int(message["recipient_count"])
    return {
        "recipient_count": sum(counts.values()),
        "recipient_states": sorted(counts),
        "recipient_state_counts": dict(counts),
    }
