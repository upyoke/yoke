"""Dry-run path-claim activation probe for the scheduler.

Reuses :func:`yoke_core.domain.path_claims_overlap.classify_overlap`
so the probe agrees with the activation gate by construction. The
conflict enumeration is a thin separate pass that surfaces the actual
sibling claims for telemetry/operator messaging. Scope is the
``(issue, refined-idea, advance)`` triple only; other triples are
explicit non-goals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
    expand_lineage,
)
from yoke_core.domain.path_claims_boundary_targets import (
    path_string_map_for_target_ids,
)


class FeasibilityOutcome(str, Enum):
    """Verdict bucket emitted by :func:`probe_advance_feasibility`."""

    FEASIBLE = "feasible"
    NO_CLAIM = "no_claim"
    BLOCKED_CROSS_ITEM_OVERLAP = "blocked_cross_item_overlap"


@dataclass(frozen=True)
class FeasibilityVerdict:
    """Result of the dry-run advance-feasibility probe."""

    outcome: FeasibilityOutcome
    reason: str
    candidate_claim_id: Optional[int] = None
    conflicting_claim_ids: List[int] = field(default_factory=list)
    conflicting_item_ids: List[str] = field(default_factory=list)
    shared_paths: List[str] = field(default_factory=list)


_PROBE_NON_TERMINAL_STATES = ("planned", "active")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _fetch_candidate_claim(
    conn: Any, item_id: int
) -> Optional[Tuple[int, str]]:
    """Most relevant exclusive non-terminal claim — prefer active over
    planned, most recently registered on a tie. Returns ``None`` when
    the path-claim tables are absent (minimal-schema test fixtures)."""
    try:
        p = _p(conn)
        row = conn.execute(
            "SELECT id, integration_target FROM path_claims "
            f"WHERE item_id = {p} AND mode = 'exclusive' "
            "AND state IN ('planned','active') "
            "ORDER BY CASE state WHEN 'active' THEN 0 ELSE 1 END, "
            "registered_at DESC LIMIT 1",
            (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        # On Postgres the missing-table error aborts the transaction; roll back
        # so the caller can keep using the same connection. SQLite does not
        # poison the transaction on a failed read, and a rollback there would
        # discard the caller's uncommitted writes — so this is Postgres-only.
        if db_backend.connection_is_postgres(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        return None
    if row is None:
        return None
    return int(row[0]), str(row[1])


def _fetch_claim_target_ids(
    conn: Any, claim_id: int
) -> List[int]:
    p = _p(conn)
    rows = conn.execute(
        f"SELECT target_id FROM path_claim_targets WHERE claim_id = {p}",
        (claim_id,),
    ).fetchall()
    return [int(r[0]) for r in rows]


def _enumerate_conflicts(
    conn: Any,
    *,
    candidate_claim_id: int,
    candidate_target_ids: List[int],
    integration_target: str,
) -> Tuple[List[int], List[str], List[str]]:
    """Same-target non-terminal claims that share at least one target
    (post-lineage) with the candidate. Used after classify_overlap
    returned INCOMPATIBLE to name the actual blockers."""
    expanded = set(expand_lineage(conn, candidate_target_ids))
    if not expanded:
        return [], [], []

    p = _p(conn)
    placeholders = ",".join(p for _ in _PROBE_NON_TERMINAL_STATES)
    rows = conn.execute(
        f"SELECT id, item_id FROM path_claims "
        f"WHERE integration_target = {p} AND mode = 'exclusive' "
        f"AND state IN ({placeholders}) AND id <> {p}",
        (integration_target, *_PROBE_NON_TERMINAL_STATES, candidate_claim_id),
    ).fetchall()

    conflicting_claim_ids: List[int] = []
    conflicting_item_ids: List[str] = []
    shared_target_ids: set[int] = set()
    seen_items: set[int] = set()
    for row in rows:
        other_id = int(row[0])
        other_item_id = row[1]
        other_targets = _fetch_claim_target_ids(conn, other_id)
        other_expanded = set(expand_lineage(conn, other_targets))
        shared = expanded & other_expanded
        if not shared:
            continue
        conflicting_claim_ids.append(other_id)
        if other_item_id is not None and int(other_item_id) not in seen_items:
            seen_items.add(int(other_item_id))
            conflicting_item_ids.append(f"YOK-{int(other_item_id)}")
        shared_target_ids.update(int(tid) for tid in shared)
    shared_path_map = path_string_map_for_target_ids(
        conn, sorted(shared_target_ids)
    )
    return (
        sorted(conflicting_claim_ids),
        sorted(conflicting_item_ids),
        sorted(shared_path_map.values()),
    )


def probe_advance_feasibility(
    conn: Any, *, item_id: int,
) -> FeasibilityVerdict:
    """Dry-run feasibility verdict for the candidate's planned
    ``advance`` path-claim activation.

    ``NO_CLAIM`` when no planned/active exclusive claim exists
    (readiness gate owns that diagnostic, so the probe passes through).
    ``FEASIBLE`` when classify_overlap is ``NONE`` or
    ``SERIAL_VIA_DEPENDENCY``. ``BLOCKED_CROSS_ITEM_OVERLAP`` with
    conflict enumeration when classify_overlap is ``INCOMPATIBLE``.
    """
    candidate = _fetch_candidate_claim(conn, item_id)
    if candidate is None:
        return FeasibilityVerdict(
            outcome=FeasibilityOutcome.NO_CLAIM,
            reason=f"no planned path-claim found for item {item_id}",
        )
    claim_id, integration_target = candidate
    target_ids = _fetch_claim_target_ids(conn, claim_id)
    if not target_ids:
        return FeasibilityVerdict(
            outcome=FeasibilityOutcome.FEASIBLE,
            reason="candidate claim has no declared targets",
            candidate_claim_id=claim_id,
        )

    classification = classify_overlap(
        conn,
        target_ids=target_ids,
        integration_target=integration_target,
        exclude_claim_id=claim_id,
        candidate_item_id=item_id,
        phase="register",
    )
    if classification is OverlapClassification.INCOMPATIBLE:
        claim_ids, item_ids, shared_paths = _enumerate_conflicts(
            conn,
            candidate_claim_id=claim_id,
            candidate_target_ids=target_ids,
            integration_target=integration_target,
        )
        return FeasibilityVerdict(
            outcome=FeasibilityOutcome.BLOCKED_CROSS_ITEM_OVERLAP,
            reason=(
                "candidate path-claim overlaps non-terminal sibling claim(s) "
                "with no serial-via-dependency edge attesting the order"
            ),
            candidate_claim_id=claim_id,
            conflicting_claim_ids=claim_ids,
            conflicting_item_ids=item_ids,
            shared_paths=shared_paths,
        )
    return FeasibilityVerdict(
        outcome=FeasibilityOutcome.FEASIBLE,
        reason=f"classify_overlap={classification.value}",
        candidate_claim_id=claim_id,
    )


__all__ = [
    "FeasibilityOutcome",
    "FeasibilityVerdict",
    "probe_advance_feasibility",
]
