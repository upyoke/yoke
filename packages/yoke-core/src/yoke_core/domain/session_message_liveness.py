"""Bulk messages reach present sessions with recent or in-flight tool activity.

Between-turns sessions remain recipients, including holders that declared a
pause. Explicit liveness flags retain their legacy selector meaning; named
anchors remain deliberate choices across every state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from yoke_contracts.session_control.liveness import (
    LIVENESS_ALL,
    LIVENESS_STATES,
)

#: What a bulk anchor resolves against when the sender names nothing.
DEFAULT_BULK_LIVENESS: tuple[str, ...] = ("active", "waiting")

#: Anchor evidence that describes a population rather than named sessions.
_PROJECT_EVIDENCE_PREFIX = "project:"
_UNIVERSE_EVIDENCE = "universe"


def bulk_message_eligible(row: Mapping[str, Any], *, now: datetime) -> bool:
    """Use the shared state model, never heartbeats or claim protection."""
    from yoke_core.domain.session_state import session_state

    state = session_state(row, now=now)
    return state["presence"] == "present" and state["activity"] in {
        "working", "between_turns"
    }


def has_bulk_anchor(selector: Any) -> bool:
    """True when the selector names a population rather than only sessions."""
    return bool(getattr(selector, "projects", None)) or bool(
        getattr(selector, "universe", False)
    )


def is_bulk_evidence(evidence: Iterable[str]) -> bool:
    """True when every anchor that matched a recipient was a bulk one."""
    entries = list(evidence)
    if not entries:
        return False
    return all(
        entry == _UNIVERSE_EVIDENCE or entry.startswith(_PROJECT_EVIDENCE_PREFIX)
        for entry in entries
    )


def applied_liveness(selector: Any) -> tuple[str, ...]:
    """Return the liveness states this selector resolves against.

    The result is what audit should show: an explicit ``--liveness`` verbatim
    (with ``all`` expanded to every state), the bulk default when the sender
    named nothing and used a bulk anchor, and every state otherwise.
    """
    requested = tuple(getattr(selector, "liveness", ()) or ())
    if requested:
        if LIVENESS_ALL in requested:
            return LIVENESS_STATES
        return tuple(state for state in LIVENESS_STATES if state in requested)
    if has_bulk_anchor(selector):
        return DEFAULT_BULK_LIVENESS
    return LIVENESS_STATES


def narrows_bulk_by_default(selector: Any) -> bool:
    """True when the bulk default — not an explicit flag — is narrowing."""
    return not tuple(getattr(selector, "liveness", ()) or ()) and has_bulk_anchor(
        selector
    )


__all__ = [
    "DEFAULT_BULK_LIVENESS",
    "bulk_message_eligible",
    "applied_liveness",
    "has_bulk_anchor",
    "is_bulk_evidence",
    "narrows_bulk_by_default",
]
