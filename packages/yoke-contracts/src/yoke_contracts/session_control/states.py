"""Wire-state literals shared by session-control models and adapters."""

from __future__ import annotations

from typing import Literal


MessageState = Literal["pending", "injected", "acknowledged", "expired", "cancelled"]
MessageListState = Literal[MessageState, "unacknowledged"]
LaunchState = Literal[
    "queued",
    "assigned",
    "launching",
    "awaiting_registration",
    "succeeded",
    "failed",
    "cancelled",
    "expired",
    "outcome_unknown",
]


__all__ = ["LaunchState", "MessageListState", "MessageState"]
