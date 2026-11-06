"""Shared primitives for the joint lifecycle gates.

Owns constants, the :class:`GateOutcome` result type, and the JSON / ISO
timestamp helpers consumed by the gate-phase siblings:

* :class:`GateOutcome` — the public result shape every gate returns.
* :func:`_safe_parse_dict` — JSON-tolerant ``raw → dict`` reader.
* :func:`_now_iso` — UTC ISO-8601 ``Z`` timestamp.

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
    ``warnings`` — non-blocking checks that degraded or were skipped.
    ``escalations`` — class escalations the joint gate would record on
    the attestation (used by the stamping step at §7.1 transition).
    """

    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    escalations: List[Dict[str, Any]] = field(default_factory=list)


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
    "_now_iso",
    "_safe_parse_dict",
]
