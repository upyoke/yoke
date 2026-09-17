"""Keeping a printed receipt to what its reader can act on.

A receipt is read by a person or an agent deciding what to do next, and most
of what makes one large is not part of that decision: a whole stored row
handed back for a one-field stamp, or the caller's own argument list echoed
to it. ``--json`` is the machine payload and is never touched here; this
trims only what the terminal prints.

Two rules keep the trim honest.

**A printed receipt never advises repeating the command.** By the time a
receipt prints, the command has already run, and for a mutation that write is
not something to replay in order to read output — the same defect as treating
a close-out as a probe. So the guidance here is about the *next* invocation's
flags, never about repeating this one, and no wording in this module may
suggest otherwise.

**Size alone never removes an actionable fact.** A failure, the recovery for
one, or an authority decision is the reason the reader is reading, so those
print in full however long they are — including when one is nested inside an
otherwise bulky value. Only bulk with nothing actionable in it is marked.
"""

from __future__ import annotations

import json
from typing import Any

#: A receipt at or under this many serialized bytes prints exactly as the
#: handler returned it. The bound is deliberately well clear of ordinary
#: receipts — a lifecycle transition, a claim, a Progress Log append — so
#: marking is reserved for the outliers.
RECEIPT_BYTE_CAP = 2000

#: Only a value at least this large is a candidate for marking. Small facts
#: always survive, so a receipt keeps the ref it touched and the status it
#: moved to even when one bulky sibling is marked.
COMPACTABLE_VALUE_BYTES = 512

#: Result keys whose value states a failure, the recovery for one, or an
#: authority decision. These print in full at any size, and a container
#: holding one anywhere inside it prints in full too: the reader is reading
#: because something needs doing, and length is not a reason to hide it.
ACTIONABLE_KEYS = frozenset(
    {
        "authority",
        "blockers",
        "conflicts",
        "denied",
        "error",
        "errors",
        "failed_checks",
        "failures",
        "findings",
        "hint",
        "next_action",
        "next_actions",
        "recovery",
        "recovery_hint",
        "refusal",
        "remediation",
        "unresolved",
        "warnings",
    }
)

#: How to get the whole envelope, stated as a flag for an invocation rather
#: than as an instruction to repeat the one that just ran.
FULL_RECEIPT_FLAG = "--json prints the whole envelope"


def _measure(value: Any) -> int:
    try:
        return len(json.dumps(value, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return 0


def carries_actionable_fact(value: Any) -> bool:
    """Whether *value* holds a failure, recovery, or authority fact anywhere."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in ACTIONABLE_KEYS and nested not in (None, [], {}, ""):
                return True
            if carries_actionable_fact(nested):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(carries_actionable_fact(entry) for entry in value)
    return False


def _marker(value: Any, size: int) -> str:
    if isinstance(value, dict):
        extent = f", {len(value)} keys"
    elif isinstance(value, (list, tuple)):
        extent = f", {len(value)} entries"
    else:
        extent = ""
    return f"<not printed: {size} bytes{extent} — {FULL_RECEIPT_FLAG}>"


def compact_receipt(result: Any) -> tuple[Any, list[str]]:
    """Return the value to print and the names of the keys it marked.

    An unchanged receipt comes back with an empty key list, including when a
    receipt is large only because it holds many small facts — there is no one
    bulky value to mark there, and shortening the facts themselves would
    remove the answer rather than its bulk.
    """
    if not isinstance(result, dict) or _measure(result) <= RECEIPT_BYTE_CAP:
        return result, []
    marked: list[str] = []
    display: dict[str, Any] = {}
    for key, value in result.items():
        size = _measure(value)
        keep = (
            size < COMPACTABLE_VALUE_BYTES
            or str(key) in ACTIONABLE_KEYS
            or carries_actionable_fact(value)
        )
        if keep:
            display[key] = value
            continue
        display[key] = _marker(value, size)
        marked.append(str(key))
    if not marked:
        return result, []
    return display, marked


def omission_advisory(marked: list[str]) -> str:
    """One line naming what printed as a marker, without advising a repeat.

    The command has already run. For a mutation, repeating it to read output
    would redo the write, so this names the flag for an invocation that needs
    the whole envelope rather than telling anyone to run this one again.
    """
    return (
        f"receipt: {', '.join(marked)} printed as a size marker to keep this "
        "readable; every failure, recovery, and authority fact is above in "
        "full. This command has already run — add --json to an invocation "
        "when you want the whole envelope, rather than repeating this one."
    )


__all__ = [
    "ACTIONABLE_KEYS",
    "COMPACTABLE_VALUE_BYTES",
    "FULL_RECEIPT_FLAG",
    "RECEIPT_BYTE_CAP",
    "carries_actionable_fact",
    "compact_receipt",
    "omission_advisory",
]
