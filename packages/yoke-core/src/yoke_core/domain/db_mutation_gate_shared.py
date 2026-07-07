"""Shared primitives for the joint lifecycle gates.

Owns constants, the :class:`GateOutcome` result type, and the JSON / ISO
timestamp helpers consumed by the gate-phase siblings:

* :class:`GateOutcome` — the public result shape every gate returns.
* :func:`_safe_parse_dict` — JSON-tolerant ``raw → dict`` reader.
* :func:`_now_iso` — UTC ISO-8601 ``Z`` timestamp.
* :data:`_NON_TERMINAL_STATUSES` — claim-holding statuses for overlap.

The front door :mod:`yoke_core.domain.db_mutation_gate` re-exports
:class:`GateOutcome` from this module so historical importers continue to
resolve. Per the sim-gap rule the re-export is direct — no
two-hop indirection through an intermediate sibling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from yoke_core.domain import db_helpers


@dataclass(frozen=True)
class GateOutcome:
    """Single gate evaluation result.

    ``passed`` — whether the gate allows the transition.
    ``errors`` — operator-facing reasons the gate blocked (empty on pass).
    ``escalations`` — class escalations the joint gate would record on
    the attestation (used by the stamping step at §7.1 transition).
    """

    passed: bool
    errors: List[str] = field(default_factory=list)
    escalations: List[Dict[str, Any]] = field(default_factory=list)


# Statuses considered "non-terminal" for the cross-ticket overlap check.
# Tickets in any of these states still hold a claim against affected
# surfaces; once a ticket reaches a terminal state its declared profile
# no longer participates in overlap detection.
_NON_TERMINAL_STATUSES = frozenset({
    "idea",
    "refining-idea",
    "refined-idea",
    "planning",
    "plan-drafted",
    "refining-plan",
    "planned",
    "implementing",
    "reviewing-implementation",
    "reviewed-implementation",
    "polishing-implementation",
    "implemented",
    "release",
    # legacy lifecycle status retained here only so a row whose
    # status='blocked' has not yet been migrated still participates in
    # overlap detection. Post-cutover the canonical block signal is
    # items.blocked=1 (orthogonal to status); a flag-blocked item still
    # holds an in-flight lifecycle position above and stays in this set
    # via that status, not via the legacy "blocked" entry.
    "blocked",
})


def _safe_parse_dict(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _now_iso() -> str:
    """Return a UTC ISO-8601 timestamp ending in ``Z``.

    Matches the rest of the governed DB-mutation gate surface (db_helpers.iso8601_now uses the
    same shape) so ``frozen_at`` and audit rows compare cleanly.
    """
    return db_helpers.iso8601_now()


__all__ = [
    "GateOutcome",
    "_NON_TERMINAL_STATUSES",
    "_now_iso",
    "_safe_parse_dict",
]
