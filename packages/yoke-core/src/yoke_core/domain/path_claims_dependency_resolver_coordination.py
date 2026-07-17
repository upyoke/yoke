"""Coordination-only awareness for path-claim overlap classification.

Sibling helper of :mod:`path_claims_dependency_resolver`. Lives in its
own module because the resolver is at the file-line cap and this slice
adds a new predicate, not a new variant of an existing helper.

A ``coordination_only`` ``item_dependencies`` edge declares the two
items touch overlapping files but no lifecycle ordering is required.
The path-claim overlap classifier consults this module to decide
whether a candidate / blocker pair with a dep edge between them should
serialize (the candidate is the DEPENDENT side of a non-coordination
edge to the blocker) or activate in parallel (every linking edge is
``coordination_only``).

The classifier walks ``item_dependencies`` **directionally**: an edge
where the candidate is the DEPENDENT party drives the candidate to
``HAS_SERIAL``; an edge where the candidate is the BLOCKER party does
not — the candidate is upstream and does not wait. The reverse-side
classification (passing the same items in reversed roles) sees the
same edge as ``HAS_SERIAL`` and serializes correctly. This matches the
hard-block dependency gate in
:func:`yoke_core.domain.check_hard_blocks.evaluate_blockers`, which
respects ``item_dependencies.dependent_item`` direction.
"""

from __future__ import annotations

import enum
from typing import Any, Optional

from yoke_core.domain.dependency_types import is_coordination_only
from yoke_core.domain.db_optional_queries import fetch_optional_rows
from yoke_core.domain.path_claims_dependency_resolver import (
    _claim_owning_item,
    _strip_sun_prefix,
)


class CoordinationClassification(enum.Enum):
    """Edge-shape between a candidate and a blocker's owning items."""

    NO_EDGE = "no_edge"
    COORDINATION_ONLY = "coordination_only"
    HAS_SERIAL = "has_serial"


def _inter_item_gate_points(
    conn: Any, *, item_a_id: int, item_b_id: int,
) -> list[str]:
    """Return every ``item_dependencies.gate_point`` whose row links the
    two items in either direction. Missing table → ``[]``.
    """
    pair = {str(item_a_id), str(item_b_id)}
    rows = fetch_optional_rows(
        conn,
        "SELECT dependent_item, blocking_item, gate_point FROM item_dependencies",
        savepoint="_yoke_item_dependencies_pair_probe",
    )
    return [
        str(gp or "")
        for d, b, gp in rows
        if pair == {_strip_sun_prefix(d), _strip_sun_prefix(b)}
    ]


def _direct_gate_points(
    conn: Any, *, dependent_item_id: int, blocking_item_id: int,
) -> list[str]:
    """Return gate points for candidate -> blocker rows only."""
    dep = str(dependent_item_id)
    blk = str(blocking_item_id)
    rows = fetch_optional_rows(
        conn,
        "SELECT dependent_item, blocking_item, gate_point FROM item_dependencies",
        savepoint="_yoke_item_dependencies_direct_probe",
    )
    return [
        str(gp or "")
        for d, b, gp in rows
        if _strip_sun_prefix(d) == dep and _strip_sun_prefix(b) == blk
    ]


def has_forward_serial_edge(
    conn: Any, *, dependent_item_id: int, blocking_item_id: int,
) -> bool:
    """Return True for candidate -> blocker non-coordination edges."""
    return any(
        not is_coordination_only(gp)
        for gp in _direct_gate_points(
            conn,
            dependent_item_id=dependent_item_id,
            blocking_item_id=blocking_item_id,
        )
    )


def classify_inter_item_edges(
    conn: Any,
    *,
    candidate_claim_id: Optional[int],
    candidate_item_id: Optional[int],
    blocking_claim_id: int,
) -> CoordinationClassification:
    """Classify the dep-edge shape between two claims' owning items.

    Directional contract — ``HAS_SERIAL`` fires only when the candidate
    is the DEPENDENT party of a non-coordination edge to the blocker.
    Returns :class:`CoordinationClassification`:

    * ``NO_EDGE`` — no ``item_dependencies`` row links the two items in
      either direction, OR the only linking non-coordination edges have
      the candidate as the BLOCKER (the upstream-of-``blocks`` case).
      The caller distinguishes the two sub-cases for itself when it
      needs to: a reverse-direction ``has_forward_serial_edge`` check
      identifies the attested-upstream sub-case so the candidate is
      allowed to activate.
    * ``COORDINATION_ONLY`` — at least one edge links the pair and every
      linking edge in either direction is ``coordination_only``. No
      path-claim mutex; parallel activation allowed; merge-time conflict
      resolution only.
    * ``HAS_SERIAL`` — at least one edge has the candidate as DEPENDENT,
      the other party as BLOCKER, and a non-coordination ``gate_point``
      (``activation`` / ``integration`` / ``closure``). The caller
      serializes the candidate behind the blocker.

    Same-item overlaps return ``NO_EDGE``: there is no
    ``item_dependencies`` edge for an item to itself, and multi-claim
    intra-item coordination is the operator's explicit
    ``--upstream-claim-id`` path, not a dep-edge concern.
    """
    if candidate_item_id is None and candidate_claim_id is not None:
        candidate_item_id = _claim_owning_item(conn, candidate_claim_id)
    blocking_item_id = _claim_owning_item(conn, blocking_claim_id)
    if candidate_item_id is None or blocking_item_id is None:
        return CoordinationClassification.NO_EDGE
    if candidate_item_id == blocking_item_id:
        return CoordinationClassification.NO_EDGE

    if has_forward_serial_edge(
        conn,
        dependent_item_id=candidate_item_id,
        blocking_item_id=blocking_item_id,
    ):
        return CoordinationClassification.HAS_SERIAL

    gate_points = _inter_item_gate_points(
        conn, item_a_id=candidate_item_id, item_b_id=blocking_item_id,
    )
    if not gate_points:
        return CoordinationClassification.NO_EDGE
    if all(is_coordination_only(gp) for gp in gate_points):
        return CoordinationClassification.COORDINATION_ONLY
    return CoordinationClassification.NO_EDGE


__all__ = [
    "CoordinationClassification",
    "classify_inter_item_edges",
    "has_forward_serial_edge",
]
