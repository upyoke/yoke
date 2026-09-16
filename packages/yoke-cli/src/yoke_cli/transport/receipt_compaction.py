"""Keeping a printed receipt to what its reader can act on.

A mutation's receipt is read by a person or an agent deciding what to do
next, and most of what makes one large is not part of that decision: a whole
stored row handed back for a one-field stamp, or the caller's own argument
list echoed to it. ``--json`` is the machine payload and is never touched
here; this trims only what the terminal prints.

Nothing is dropped silently. Each value left out is replaced in place by a
marker naming its size and the flag that returns it, so a reader sees that
something was omitted and how to get it, and a consumer that indexes into one
fails immediately rather than reading a wrong answer from a shortened value.
"""

from __future__ import annotations

import json
from typing import Any

#: A receipt at or under this many serialized bytes prints exactly as the
#: handler returned it. The bound is deliberately well clear of ordinary
#: receipts — a lifecycle transition, a claim, a Progress Log append — so
#: compaction is reserved for the outliers and never costs a second call to
#: recover a fact that would have fit.
RECEIPT_BYTE_CAP = 2000

#: Only a value at least this large is a candidate for omission. Small facts
#: always survive, so a receipt keeps the status it moved to, the ref it
#: touched, and any blocker it reported even when one bulky sibling goes.
COMPACTABLE_VALUE_BYTES = 512

#: How to read what was left out. One spelling, used in the marker and in the
#: advisory line the writer prints beside it.
FULL_RECEIPT_RECOVERY = "rerun with --json"


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
    return f"<omitted: {size} bytes{extent} — {FULL_RECEIPT_RECOVERY}>"


def compact_receipt(result: Any) -> tuple[Any, list[str]]:
    """Return the value to print and the names of the keys it left out.

    An unchanged receipt comes back with an empty key list, including the
    case where a receipt is large only because it holds many small facts —
    there is no one bulky value to drop there, and shortening the facts
    themselves would remove the answer rather than its bulk.
    """
    if not isinstance(result, dict) or _measure(result) <= RECEIPT_BYTE_CAP:
        return result, []
    omitted: list[str] = []
    display: dict[str, Any] = {}
    for key, value in result.items():
        size = _measure(value)
        if size >= COMPACTABLE_VALUE_BYTES:
            display[key] = _marker(value, size)
            omitted.append(str(key))
            continue
        display[key] = value
    if not omitted:
        return result, []
    return display, omitted


def omission_advisory(omitted: list[str]) -> str:
    """One line naming what the printed receipt left out, and how to read it."""
    return (
        f"receipt: omitted {', '.join(omitted)} to keep this readable; "
        f"{FULL_RECEIPT_RECOVERY} for the full envelope"
    )


__all__ = [
    "COMPACTABLE_VALUE_BYTES",
    "FULL_RECEIPT_RECOVERY",
    "RECEIPT_BYTE_CAP",
    "compact_receipt",
    "omission_advisory",
]
