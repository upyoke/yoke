"""Opaque native wake instruction shared by relay and acceptance evidence."""

from __future__ import annotations

import hashlib


#: The registered command the woken turn runs first. It is the cheapest call
#: that still goes through the harness tool surface, and going through that
#: surface is the entire point.
WAKE_DELIVERY_COMMAND = "yoke sessions touch"


def native_wake_instruction(message_id: str) -> str:
    """Name the tool call that delivers the message, then the receipt it owes.

    A wake exists so a turn takes delivery of a message, and the delivery is
    not the resume: the installed hook injects the envelope, the hook runs
    only when the turn makes a tool call, and the turn has only finished the
    job once the envelope's fixed acknowledgement command has run.

    Both halves had to be asked for. A prompt that merely announced the
    message left the acknowledgement to the turn's own disposition, and a
    session whose transcript is a conversation rather than a worker mandate
    answered in prose and ended without acknowledging. A prompt that then
    named the acknowledgement still assumed an envelope would be there to
    acknowledge — and a turn that reasons and answers without touching a
    tool never fires the hook that would have attached one. Three accepted
    resumes against one idle session produced three turns and zero
    injections that way. So the instruction names the tool call itself,
    first, before anything else the turn might do.

    It also names the one case where acknowledging would be wrong. An
    unconditional "acknowledge now" turns a wake whose envelope never
    arrived into a receipt that reports delivery which did not happen, and
    the plane would stop re-waking on the strength of it. The body itself
    stays in Yoke: only the message identity crosses into native traffic.
    """
    return (
        f"Yoke message {message_id} is pending for this session, and this turn "
        "was started to deliver it. Delivery happens inside a tool call: run "
        f"`{WAKE_DELIVERY_COMMAND}` as this turn's first action, and the "
        "installed Yoke hook injects that message's envelope into this turn. "
        "Then run the fixed acknowledgement command the envelope names before "
        "you answer or end this turn. If no envelope was injected, do not "
        "acknowledge; report that instead."
    )


def native_wake_instruction_sha256(message_id: str) -> str:
    return hashlib.sha256(
        native_wake_instruction(message_id).encode("utf-8")
    ).hexdigest()


__all__ = [
    "WAKE_DELIVERY_COMMAND",
    "native_wake_instruction",
    "native_wake_instruction_sha256",
]
