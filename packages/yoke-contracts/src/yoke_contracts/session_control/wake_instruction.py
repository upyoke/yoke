"""Opaque native wake instruction shared by relay and acceptance evidence."""

from __future__ import annotations

import hashlib


def native_wake_instruction(message_id: str) -> str:
    """Name the receipt and the one action the woken turn owes it.

    A wake exists so a turn takes delivery of a message, and the delivery is
    not the resume: the installed hook injects the envelope into the turn,
    and the turn has only finished the job once the envelope's fixed
    acknowledgement command has run. A prompt that merely announced the
    message left that last step to the turn's own disposition, and a session
    whose transcript is a conversation rather than a worker mandate answered
    the announcement in prose and ended without acknowledging — so the plane
    had to wake it a second time to collect a receipt the first wake had
    already earned. The prompt therefore names the action it needs.

    It also names the one case where acknowledging would be wrong. An
    unconditional "acknowledge now" turns a wake whose envelope never
    arrived into a receipt that reports delivery which did not happen, and
    the plane would stop re-waking on the strength of it. The body itself
    stays in Yoke: only the message identity crosses into native traffic.
    """
    return (
        f"Yoke message {message_id} is pending for this session, and this turn "
        "was started to deliver it. The installed Yoke hook injects that "
        "message's envelope into this turn: run the fixed acknowledgement "
        "command the envelope names before you answer or end this turn. If no "
        "envelope was injected, do not acknowledge; report that instead."
    )


def native_wake_instruction_sha256(message_id: str) -> str:
    return hashlib.sha256(
        native_wake_instruction(message_id).encode("utf-8")
    ).hexdigest()


__all__ = ["native_wake_instruction", "native_wake_instruction_sha256"]
