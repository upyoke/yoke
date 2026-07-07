"""Classify ``release_reason_intent`` strings as non-terminal vs terminal.

A work-claim release carries a ``release_reason_intent`` that describes why
the holding session let the claim go. Most intents are *terminal*: the
session has finished its turn on the item and an unattended routing sweep
may safely re-route. A small closed set is *non-terminal*: the session
intends to resume on the item the moment its blocking precondition clears,
and routing must defend the prior ownership.

The incident motivated this split: a second session ran a
``/yoke charge`` offer sweep while the first session was paused on a
readiness check, and the offer surface treated the released claim as a
generic "available" item. The router then handed the same item to the
second session, and the first session resumed onto a target it no longer
owned. ``readiness-check-blocked`` is the day-1 non-terminal value.

``idea-complete`` is terminal: ``/yoke idea`` finishes its draft and any
follow-up is a fresh refinement session. ``operator-override`` is terminal:
the operator already decided to seize the claim.

Source-of-truth callouts: ``sessions_lifecycle_release.py``
``_RELEASE_REASON_SCHEMA_MAP`` seeds the terminal set;
``idea_claim_events.py`` ``RELEASE_REASON_IDEA_COMPLETE`` and
``sessions_lifecycle_release_operator.py`` supply the two extras.
Unknown intents fall back to ``"terminal"`` semantics so a typo never
silently defends ownership.
"""

from __future__ import annotations

from typing import Optional


NON_TERMINAL_RELEASE_INTENTS: frozenset[str] = frozenset({
    "readiness-check-blocked",
})


TERMINAL_RELEASE_INTENTS: frozenset[str] = frozenset({
    "handoff-to-polish",
    "handoff-to-usher",
    "handed_off",
    "handoff",
    "finalize-exit",
    "offer-override",
    "released",
    "completed",
    "reclaimed",
    "expired",
    "session_ended",
    "idea-complete",
    "operator-override",
    "usher-halt-merge-failure",
    "usher-halt-deploy-infra-failure",
    "usher-halt-deploy-stage-failure",
    "usher-halt-unexpected",
})


def is_non_terminal_release_intent(intent: Optional[str]) -> bool:
    """Return True when ``intent`` belongs to the non-terminal closed set."""
    if intent is None:
        return False
    return intent in NON_TERMINAL_RELEASE_INTENTS


def classify_release_intent(intent: Optional[str]) -> str:
    """Return ``"non_terminal"``, ``"terminal"``, or ``"unknown"`` for ``intent``.

    Unknown intents fall back to ``"terminal"`` semantics so callers never
    silently defend ownership for an unclassified intent.
    """
    if intent in NON_TERMINAL_RELEASE_INTENTS:
        return "non_terminal"
    if intent in TERMINAL_RELEASE_INTENTS:
        return "terminal"
    return "unknown"
