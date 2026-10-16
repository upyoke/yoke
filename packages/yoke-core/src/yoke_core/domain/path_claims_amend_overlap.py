"""Dependency-aware widen-overlap helper for path claims.

The amendment surface :func:`yoke_core.domain.path_claims_amend.widen`
consults this module to decide what to do when newly requested coverage
overlaps another non-terminal claim on the same integration target. Only the
paths a widen adds are classified: overlap the claim already held is governed
by the activation and dependency gates, so a dependency edge authored after
that overlap existed never refuses a widen whose new paths overlap nothing. The register-time classifier
(:func:`yoke_core.domain.path_claims_overlap.classify_overlap`) tells
the caller *whether* the overlap is compatible; this helper turns that
into a structured widen decision: whether the widen may proceed, whether
the resulting claim must remain or become ``blocked``, and which
upstream claim ids the amendment payload should record.

The contract preserves three invariants:

* Un-attested same-target overlap still rejects. A widen
  that would cover paths held by another non-terminal claim without an
  authored ``item_dependencies`` edge must not silently downgrade the
  candidate.
* An ``active`` claim does not silently downgrade to ``blocked``.
  If a newly discovered overlap would require waiting, the amendment is
  rejected and the operator handles the ordering explicitly.
* ``coordination_only`` overlaps and candidate-as-blocker reverse-
  direction attestations continue to allow upstream/parallel progress
  — these classify the widen as allowed without changing claim
  state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
    expand_lineage,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class WidenOverlapDecision:
    """Structured widen-overlap outcome consumed by ``widen``.

    * ``allowed`` — true when the widen may proceed (insert new target
      rows and record the amendment).
    * ``block_claim`` — true when the post-widen claim must be in
      ``state='blocked'`` with a refreshed ``blocked_reason`` naming the
      chosen serial upstream.
    * ``upstream_claim_ids`` — every overlapping non-terminal claim
      attested by a forward-direction (candidate -> blocker) non-
      coordination ``item_dependencies`` edge. Empty list when the
      widen does not need to wait on anything.
    * ``overlapping_claim_ids`` — every non-terminal claim on the same
      integration target whose declared coverage intersects the
      candidate's post-widen union. Recorded on the amendment payload
      for audit only; it never decides the outcome.
    * ``reason`` — actionable rejection text when ``allowed`` is false;
      ``None`` otherwise.
    """

    allowed: bool
    block_claim: bool
    upstream_claim_ids: List[int]
    overlapping_claim_ids: List[int]
    reason: Optional[str] = None


def classify_widen_overlap(
    conn: Any,
    *,
    claim_id: int,
    new_target_ids: Sequence[int],
    union_target_ids: Sequence[int],
    integration_target: str,
    candidate_item_id: Optional[int],
    current_claim_state: str,
) -> WidenOverlapDecision:
    """Decide the widen-overlap outcome for the newly added coverage.

    ``new_target_ids`` are the target ids about to be inserted; only they
    are classified. ``union_target_ids`` (declared plus new) feeds the
    audit-only ``overlapping_claim_ids``. The candidate's item identity
    and claim state drive the directional dep-graph walk and the
    active-claim guard.

    The function is read-only; mutation is the caller's responsibility,
    gated on ``WidenOverlapDecision.allowed``.
    """
    overlapping = _list_overlapping_claim_ids(
        conn,
        candidate_target_ids=union_target_ids,
        integration_target=integration_target,
        exclude_claim_id=claim_id,
    )
    new_overlaps = _new_path_overlaps(
        conn,
        new_target_ids=new_target_ids,
        integration_target=integration_target,
        exclude_claim_id=claim_id,
    )

    classification = classify_overlap(
        conn,
        target_ids=new_target_ids,
        integration_target=integration_target,
        exclude_claim_id=claim_id,
        phase="register",
        candidate_item_id=candidate_item_id,
    )

    if classification is OverlapClassification.INCOMPATIBLE:
        return WidenOverlapDecision(
            allowed=False,
            block_claim=False,
            upstream_claim_ids=[],
            overlapping_claim_ids=overlapping,
            reason=(
                f"widen rejected for claim {claim_id}: new coverage overlaps "
                f"a non-terminal claim on {integration_target!r} with no "
                f"item_dependencies edge ({_describe(new_overlaps)}). "
                "Author a depends-on/blocks edge with rationale "
                "(coordination_only when edits do not conflict semantically; "
                "activation/integration/closure for serial ordering), or "
                "drop those paths from the widen."
            ),
        )

    if classification is OverlapClassification.NONE:
        return WidenOverlapDecision(
            allowed=True,
            block_claim=False,
            upstream_claim_ids=[],
            overlapping_claim_ids=overlapping,
        )

    upstreams = _serial_upstreams_for(
        conn,
        candidate_item_id=candidate_item_id,
        overlapping_claim_ids=sorted(new_overlaps),
    )

    if not upstreams:
        # ``classify_overlap`` returned ``SERIAL_VIA_DEPENDENCY`` but no
        # candidate -> blocker forward edge justifies serializing. The
        # most common cause is an active override on the pair or a
        # candidate-as-blocker reverse-direction attestation that the
        # classifier collapses to ``SERIAL_VIA_DEPENDENCY`` for the
        # other side. The candidate does not need to wait; the widen
        # proceeds without changing claim state.
        return WidenOverlapDecision(
            allowed=True,
            block_claim=False,
            upstream_claim_ids=[],
            overlapping_claim_ids=overlapping,
        )

    if current_claim_state == "active":
        blocking = {cid: new_overlaps[cid] for cid in upstreams}
        return WidenOverlapDecision(
            allowed=False,
            block_claim=False,
            upstream_claim_ids=upstreams,
            overlapping_claim_ids=overlapping,
            reason=(
                f"widen rejected for claim {claim_id}: claim is "
                "state='active' but new coverage overlaps non-terminal "
                f"upstream claim(s) {upstreams!r} ({_describe(blocking)}). "
                "Active claims cannot be silently downgraded to blocked. "
                "Drop those paths from the widen, wait for the upstream to "
                "release, or coordinate the ordering with the upstream "
                "holder before amending."
            ),
        )

    return WidenOverlapDecision(
        allowed=True,
        block_claim=True,
        upstream_claim_ids=upstreams,
        overlapping_claim_ids=overlapping,
    )


def _new_path_overlaps(
    conn: Any,
    *,
    new_target_ids: Sequence[int],
    integration_target: str,
    exclude_claim_id: int,
) -> Dict[int, List[str]]:
    """Map each overlapping claim id to the new paths that intersect it."""
    overlaps: Dict[int, List[str]] = {}
    for target_id in new_target_ids:
        claim_ids = _list_overlapping_claim_ids(
            conn,
            candidate_target_ids=[target_id],
            integration_target=integration_target,
            exclude_claim_id=exclude_claim_id,
        )
        if not claim_ids:
            continue
        row = conn.execute(
            f"SELECT path_string FROM path_targets WHERE id = {_p(conn)}",
            (int(target_id),),
        ).fetchone()
        path = str(row[0]) if row else f"target {target_id}"
        for other_id in claim_ids:
            overlaps.setdefault(other_id, []).append(path)
    return overlaps


def _describe(overlaps: Dict[int, List[str]]) -> str:
    return "; ".join(
        f"claim {cid} <- new path(s) {', '.join(repr(p) for p in paths)}"
        for cid, paths in sorted(overlaps.items())
    )


def chosen_serial_upstream(upstream_claim_ids: Sequence[int]) -> Optional[int]:
    """Pick the deterministic ``blocked_reason`` upstream from a set.

    The smallest claim id wins. Returns ``None`` when the input is empty
    so the caller can branch on the no-upstream case.
    """
    if not upstream_claim_ids:
        return None
    return sorted(int(c) for c in upstream_claim_ids)[0]


def _list_overlapping_claim_ids(
    conn: Any,
    *,
    candidate_target_ids: Sequence[int],
    integration_target: str,
    exclude_claim_id: int,
) -> List[int]:
    """Find every non-terminal claim on the same integration target whose
    declared coverage intersects the given targets (lineage-aware).
    ``exclude_claim_id`` removes the candidate's own claim from the
    result.
    """
    expanded = expand_lineage(conn, candidate_target_ids)
    if not expanded:
        return []
    p = _p(conn)
    placeholders = ",".join(p for _ in expanded)
    rows = conn.execute(
        f"SELECT DISTINCT pct.claim_id FROM path_claim_targets pct "
        f"JOIN path_claims pc ON pc.id = pct.claim_id "
        f"WHERE pc.integration_target = {p} "
        f"AND pc.state IN ('planned', 'blocked', 'active') "
        f"AND pc.mode <> 'exception' "
        f"AND pct.target_id IN ({placeholders}) "
        f"AND pc.id <> {p} "
        f"ORDER BY pct.claim_id",
        (integration_target, *expanded, exclude_claim_id),
    ).fetchall()
    return [int(r[0]) for r in rows]


def _serial_upstreams_for(
    conn: Any,
    *,
    candidate_item_id: Optional[int],
    overlapping_claim_ids: Sequence[int],
) -> List[int]:
    """Return overlapping claim ids attested by a forward-direction
    (candidate -> blocker) non-coordination ``item_dependencies`` edge.
    """
    if candidate_item_id is None or not overlapping_claim_ids:
        return []
    from yoke_core.domain.path_claims_dependency_resolver import (
        _claim_owning_item,
    )
    from yoke_core.domain.path_claims_dependency_resolver_coordination import (
        has_forward_serial_edge,
    )

    upstreams: List[int] = []
    for other_id in overlapping_claim_ids:
        blocker_item = _claim_owning_item(conn, int(other_id))
        if blocker_item is None:
            continue
        if has_forward_serial_edge(
            conn,
            dependent_item_id=int(candidate_item_id),
            blocking_item_id=int(blocker_item),
        ):
            upstreams.append(int(other_id))
    return upstreams


__all__ = [
    "WidenOverlapDecision",
    "chosen_serial_upstream",
    "classify_widen_overlap",
]
