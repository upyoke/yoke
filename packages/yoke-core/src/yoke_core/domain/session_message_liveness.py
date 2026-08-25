"""Which liveness states a recipient selector resolves against.

An anchor that names sessions one at a time is a deliberate choice, so it
resolves against every liveness state. A bulk anchor is not: ``--project``
and ``--universe`` describe a population rather than a list, and the
population an operator means when broadcasting is the sessions currently
working. Resolving bulk anchors against ended sessions turns one directive
into a wake for every session that ever ran under that project.

So bulk anchors default to ``active``, and an explicit ``--liveness``
widens them deliberately. ``all`` is the widening sentinel that restores
the unfiltered population.
"""

from __future__ import annotations

from typing import Any, Iterable

from yoke_contracts.session_control.liveness import (
    LIVENESS_ALL,
    LIVENESS_STATES,
)

#: What a bulk anchor resolves against when the sender names nothing.
DEFAULT_BULK_LIVENESS: tuple[str, ...] = ("active",)

#: Anchor evidence that describes a population rather than named sessions.
_PROJECT_EVIDENCE_PREFIX = "project:"
_UNIVERSE_EVIDENCE = "universe"


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
    "applied_liveness",
    "has_bulk_anchor",
    "is_bulk_evidence",
    "narrows_bulk_by_default",
]
