"""Condensing the one kind of receipt field that answers nothing.

The default human writer prints every successful result, reads included, and
a read's value IS the answer the caller asked for — its body, its
instructions, the commands it emits to run next. So nothing here decides what
to print by looking at size, or by guessing which keys carry meaning: no
list of key names can enumerate what is semantically load-bearing, and the
cost of getting that list wrong is a destroyed answer rather than a long one.

Condensing applies only where a specific function is known to return a
specific field that restates state the caller did not ask for.
:data:`REDUNDANT_RECEIPT_FIELDS` names those pairs and nothing else, so the
failure mode of an unlisted case is a receipt that stays long — never an
answer that goes missing. Every other function, and every other field of a
listed one, prints exactly as the handler returned it.

**A printed receipt never advises repeating the command.** By the time a
receipt prints, the command has already run, and for a mutation that write is
not something to replay in order to read output. Guidance here is about the
*next* invocation's flags, never about repeating this one.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

#: Receipt fields that restate state the caller did not ask for, keyed by the
#: function that returns them. This is deliberately a short list of verified
#: cases rather than an attempt to classify every payload:
#:
#: ``sessions.touch`` stamps a heartbeat or a mode and hands back all 61
#: columns of the session row to confirm it — 2,512 bytes to report that one
#: field moved. The caller named the change in its own arguments and the
#: receipt's ``success`` reports the outcome, so the row itself answers
#: nothing that was asked.
#:
#: Add an entry only with a measurement showing the field restates state the
#: caller did not request. A read's content, and any command or instruction a
#: result emits for the caller to run, never qualify.
REDUNDANT_RECEIPT_FIELDS: Mapping[str, tuple[str, ...]] = {
    "sessions.touch": ("session",),
}

#: A listed field under this many serialized bytes prints as-is; marking it
#: would trade a readable value for a longer sentence about the value.
CONDENSE_ABOVE_BYTES = 512

#: How to get the whole envelope, stated as a flag for an invocation rather
#: than as an instruction to repeat the one that just ran.
FULL_RECEIPT_FLAG = "--json prints the whole envelope"


def _measure(value: Any) -> int:
    try:
        return len(json.dumps(value, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return 0


def _marker(value: Any, size: int) -> str:
    if isinstance(value, dict):
        extent = f", {len(value)} keys"
    elif isinstance(value, (list, tuple)):
        extent = f", {len(value)} entries"
    else:
        extent = ""
    return f"<not printed: {size} bytes{extent} — {FULL_RECEIPT_FLAG}>"


def compact_receipt(function: str, result: Any) -> tuple[Any, list[str]]:
    """Return the value to print and the names of the fields it condensed.

    A function with no entry in :data:`REDUNDANT_RECEIPT_FIELDS` — which is
    every read — comes back untouched with an empty list, whatever its size.
    """
    redundant = REDUNDANT_RECEIPT_FIELDS.get(str(function or ""))
    if not redundant or not isinstance(result, dict):
        return result, []
    condensed: list[str] = []
    display = dict(result)
    for field in redundant:
        if field not in display:
            continue
        size = _measure(display[field])
        if size <= CONDENSE_ABOVE_BYTES:
            continue
        display[field] = _marker(display[field], size)
        condensed.append(field)
    if not condensed:
        return result, []
    return display, condensed


def omission_advisory(condensed: list[str]) -> str:
    """One line naming what printed as a marker, without advising a repeat.

    The command has already run. For a mutation, repeating it to read output
    would redo the write, so this names the flag for an invocation that needs
    the whole envelope rather than telling anyone to run this one again.
    """
    return (
        f"receipt: {', '.join(condensed)} restates stored state this command "
        "did not change on request, so it printed as a size marker. This "
        "command has already run — add --json to an invocation when you want "
        "the whole envelope, rather than repeating this one."
    )


__all__ = [
    "CONDENSE_ABOVE_BYTES",
    "FULL_RECEIPT_FLAG",
    "REDUNDANT_RECEIPT_FIELDS",
    "compact_receipt",
    "omission_advisory",
]
