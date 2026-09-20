"""The routine read of one message, and the fields that narrow it.

A recipient opening its mail wants the body, who sent it, and the command
that acknowledges it. The delivery-attempt log answers a different
question — a sender chasing a message that never landed — and it grows
with every redelivery, so on a busy fleet it is both the largest part of
the answer and the least likely part to be wanted.

The routine read therefore serves the whole body beside a bounded tail of
the attempt log, and names the count it held back plus the command that
serves it. ``detail="full"`` serves every attempt. A caller that already
knows which part it wants names the fields instead and gets exactly those.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.read_detail import DETAIL_FULL


#: Attempt rows the routine read keeps. Enough to show the shape of a
#: delivery problem; small enough that a message with hundreds of
#: redelivery rows still reads as mail rather than as a log.
ROUTINE_ATTEMPT_ROWS: int = 5

#: Key naming how many attempt rows the routine read held back, and the
#: key naming the command that serves them. Both are absent when nothing
#: was withheld, so their presence is the signal.
ATTEMPTS_WITHHELD_KEY: str = "attempts_withheld"
ATTEMPTS_WITHHELD_READ_KEY: str = "attempts_withheld_read"


def unknown_message_fields(
    message: Mapping[str, Any],
    fields: Sequence[str],
) -> list[str]:
    """Return the requested field names this message does not carry."""
    return [name for name in fields if name not in message]


def project_message(
    message: Mapping[str, Any],
    *,
    fields: Sequence[str] = (),
    detail: str = "",
) -> dict[str, Any]:
    """Serve the fields a caller named, or the routine answer.

    Named fields win over ``detail``: a caller asking for ``body`` has
    already said what it wants, and adding an attempt bound to that answer
    would only put something back that it did not ask for.
    """
    if fields:
        return {name: message[name] for name in fields if name in message}
    projected = dict(message)
    if detail == DETAIL_FULL:
        return projected
    attempts = list(projected.get("attempts") or ())
    withheld = len(attempts) - ROUTINE_ATTEMPT_ROWS
    if withheld <= 0:
        return projected
    projected["attempts"] = attempts[-ROUTINE_ATTEMPT_ROWS:]
    projected[ATTEMPTS_WITHHELD_KEY] = withheld
    projected[ATTEMPTS_WITHHELD_READ_KEY] = (
        f"yoke messages get {message.get('message_id')} --full"
    )
    return projected


__all__ = [
    "ATTEMPTS_WITHHELD_KEY",
    "ATTEMPTS_WITHHELD_READ_KEY",
    "ROUTINE_ATTEMPT_ROWS",
    "project_message",
    "unknown_message_fields",
]
