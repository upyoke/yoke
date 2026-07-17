"""Status-keyed map of the gate families the authoritative status gate runs.

:data:`STATUS_GATE_POINTS` is derived from the same target-set constants
each gate runner consults at write time, so a reader serving the workflow
definition (``workflows.definition.get``) and the gate composer
(:mod:`yoke_core.domain.backlog_authoritative_status_gate`) cannot drift
apart: a gate family fires at a status exactly when this map says it does.

Two of the wiring constants live here because this module is their single
source: the composer imports :data:`PLAN_SIMULATION_TARGETS` and
:data:`QA_VERIFICATION_TARGETS` for its own dispatch, and the map is built
from the identical objects. The remaining families are imported from the
modules whose gate code checks them.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Tuple

from yoke_core.domain.backlog_architecture_gate_runner import (
    _ARCHITECTURE_GATE_TARGETS,
)
from yoke_core.domain.backlog_db_mutation_gate_runner import (
    _DB_MUTATION_GATE_TARGETS,
    _PROSE_CHECK_TARGETS,
)
from yoke_core.domain.lifecycle_progression import EPIC_PROGRESSION

try:
    from yoke_core.domain.path_claims_gate_boundary import (
        _GATED_TARGETS as _PATH_CLAIM_BOUNDARY_TARGETS,
    )
except ImportError:  # pragma: no cover - mirrors the composer's fail-open
    # The composer runs no boundary gate when the helper is unimportable,
    # so the map honestly serves none either.
    _PATH_CLAIM_BOUNDARY_TARGETS = ()

# Owned here; consumed by the composer's dispatch (see module docstring).
PLAN_SIMULATION_TARGETS = frozenset({"planned"})
QA_VERIFICATION_TARGETS = frozenset({
    "reviewed-implementation",
    "implemented",
    "release",
    "done",
})

# Gate-family ids. The three the composer aggregates at
# reviewed-implementation reuse its ``gate_id`` strings verbatim.
GATE_DB_CLAIM_PROSE = "db_claim_prose"
GATE_DB_MUTATION = "db_mutation"
GATE_ARCHITECTURE_IMPACT = "architecture_impact"
GATE_PATH_CLAIM_BOUNDARY = "path_claim_boundary"
GATE_PLAN_SIMULATION = "plan_simulation"
GATE_QA_VERIFICATION = "qa_verification"

# (family, the target statuses that family's gate code checks against),
# in the composer's evaluation order.
_FAMILY_TARGETS: Tuple[Tuple[str, frozenset], ...] = (
    (GATE_DB_CLAIM_PROSE, frozenset(_PROSE_CHECK_TARGETS)),
    (GATE_DB_MUTATION, frozenset(_DB_MUTATION_GATE_TARGETS)),
    (GATE_ARCHITECTURE_IMPACT, frozenset(_ARCHITECTURE_GATE_TARGETS)),
    (GATE_PATH_CLAIM_BOUNDARY, frozenset(_PATH_CLAIM_BOUNDARY_TARGETS)),
    (GATE_PLAN_SIMULATION, PLAN_SIMULATION_TARGETS),
    (GATE_QA_VERIFICATION, QA_VERIFICATION_TARGETS),
)


def _build_status_gate_points() -> Mapping[str, Tuple[str, ...]]:
    points: Dict[str, List[str]] = {}
    for family, targets in _FAMILY_TARGETS:
        for status in targets:
            points.setdefault(status, []).append(family)
    # Keys in epic-progression order (the superset progression); any gated
    # status outside it (none today) trails alphabetically rather than
    # silently dropping.
    ordered = [s for s in EPIC_PROGRESSION if s in points]
    ordered += sorted(s for s in points if s not in EPIC_PROGRESSION)
    return {status: tuple(points[status]) for status in ordered}


#: target status -> gate families evaluated there, in evaluation order.
STATUS_GATE_POINTS: Mapping[str, Tuple[str, ...]] = _build_status_gate_points()


__all__ = [
    "GATE_ARCHITECTURE_IMPACT",
    "GATE_DB_CLAIM_PROSE",
    "GATE_DB_MUTATION",
    "GATE_PATH_CLAIM_BOUNDARY",
    "GATE_PLAN_SIMULATION",
    "GATE_QA_VERIFICATION",
    "PLAN_SIMULATION_TARGETS",
    "QA_VERIFICATION_TARGETS",
    "STATUS_GATE_POINTS",
]
