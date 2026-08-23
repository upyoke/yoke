"""Opaque native wake instruction shared by relay and acceptance evidence."""

from __future__ import annotations

import hashlib


def native_wake_instruction(message_id: str) -> str:
    """Name only the durable receipt; the message body stays in Yoke."""
    return f"Yoke message {message_id}: check your Yoke messages."


def native_wake_instruction_sha256(message_id: str) -> str:
    return hashlib.sha256(
        native_wake_instruction(message_id).encode("utf-8")
    ).hexdigest()


__all__ = ["native_wake_instruction", "native_wake_instruction_sha256"]
