"""Opaque native wake instruction shared by relay and acceptance evidence."""

from __future__ import annotations

import hashlib


#: The registered command the woken turn runs first. It goes through the
#: harness tool surface, which is what fires the hook, and it returns the
#: message body itself, which is what makes the read independent of the hook.
WAKE_DELIVERY_COMMAND = "yoke messages get"

#: The fixed receipt the woken turn owes once it has read the message.
WAKE_ACKNOWLEDGE_COMMAND = "yoke messages acknowledge"


def native_wake_instruction(message_id: str) -> str:
    """Name the tool call that delivers the message, then the receipt it owes.

    A wake exists so a turn takes delivery of a message, and the delivery is
    not the resume: it happens inside a tool call, and the turn has only
    finished the job once the acknowledgement command has run.

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

    What that named call must not be is a call whose only delivery is the
    hook injection. Hook injection consumes a pending receipt in whatever
    turn is making tool calls at the time — including the outgoing turn that
    is already ending when the wake is opened — so a resumed turn told to
    expect an injection can find that its own envelope was handed to the
    turn it replaced, and report a wake that delivered nothing. Naming a
    command that returns the message body makes the read deterministic: the
    hook may still attach the same envelope, but the turn no longer depends
    on it. For the same reason the acknowledgement command is named here
    rather than left to the envelope to carry.

    It still names the one case where acknowledging would be wrong. An
    unconditional "acknowledge now" turns a wake whose message never arrived
    into a receipt that reports delivery which did not happen, and the plane
    would stop re-waking on the strength of it. The body itself stays in
    Yoke: only the message identity crosses into native traffic.
    """
    return (
        f"Yoke message {message_id} is pending for this session, and this turn "
        "was started to deliver it. Delivery happens inside a tool call: run "
        f"`{WAKE_DELIVERY_COMMAND} {message_id} --json` as this turn's first "
        "action and read the message body it returns. The installed Yoke hook "
        "may also inject the same envelope into that call; that is the same "
        "message, not a second one, and the read stands whether or not it "
        "happens. Then run "
        f"`{WAKE_ACKNOWLEDGE_COMMAND} {message_id}` before you answer or end "
        "this turn. If the read reported no such message, do not acknowledge; "
        "report that instead."
    )


def native_wake_instruction_sha256(message_id: str) -> str:
    return hashlib.sha256(
        native_wake_instruction(message_id).encode("utf-8")
    ).hexdigest()


__all__ = [
    "WAKE_ACKNOWLEDGE_COMMAND",
    "WAKE_DELIVERY_COMMAND",
    "native_wake_instruction",
    "native_wake_instruction_sha256",
]
