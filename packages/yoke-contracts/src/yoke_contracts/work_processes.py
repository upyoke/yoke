"""Registered work-claim process keys shared by CLI and domain.

Client packages (``yoke_cli``) must not import ``yoke_core``. The key
vocabulary lives here so both the strategy-claim release adapter and the
domain registry speak one list without crossing the product boundary.
"""

from __future__ import annotations

from typing import List

PROCESS_STRATEGIZE = "STRATEGIZE"
PROCESS_FEED = "FEED"
PROCESS_DOCTOR = "DOCTOR"

KNOWN_PROCESS_KEYS = frozenset(
    {PROCESS_STRATEGIZE, PROCESS_FEED, PROCESS_DOCTOR}
)


def is_known_process(process_key: str) -> bool:
    return process_key in KNOWN_PROCESS_KEYS


def list_processes() -> List[str]:
    """Return registered process keys in stable sorted order."""
    return sorted(KNOWN_PROCESS_KEYS)


__all__ = [
    "KNOWN_PROCESS_KEYS",
    "PROCESS_DOCTOR",
    "PROCESS_FEED",
    "PROCESS_STRATEGIZE",
    "is_known_process",
    "list_processes",
]
