"""Repair pass for path claims stranded in ``state='blocked'``.

Under the no-mutex contract, a path claim never lands in
``state='blocked'`` for either of the two cases this sweep flips:

* **Coord-only-only.** Every linking ``item_dependencies`` edge between
  candidate and blocker is ``coordination_only``. Pre-contract
  registration produced this shape; the upstream-release propagator
  left the row blocked.
* **Upstream-of-``blocks``.** The candidate is the BLOCKER side of a
  non-coordination edge and has no DEPENDENT-direction non-coordination
  edge. Pre-directional registration treated the bidirectional walk
  as a serial constraint on both parties; the directional rewrite
  flips the candidate-side row back to ``planned`` because the
  candidate is upstream and does not wait.

This helper sweeps an item's non-terminal claims at advance-time and
flips any ``state='blocked'`` row whose current overlap classifies as
:class:`OverlapClassification.NONE` over to ``state='planned'``,
clearing the stale ``blocked_reason``. Rows whose classification is
``SERIAL_VIA_DEPENDENCY`` or ``INCOMPATIBLE`` are left alone — real
``activation`` / ``integration`` / ``closure`` blocks, explicit
``--upstream-claim-id`` pointers, and live ``PathClaimOverride`` rows
all continue to hold the door lock.

Each repair emits ``PathClaimCoordinationOnlyRepaired`` with a
``directional_release`` boolean in the context: ``true`` for the
upstream-of-``blocks`` flip, ``false`` for the legacy coord-only flip.

Idempotent: re-running on an item with no flippable blocked rows is a
no-op.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional

from yoke_core.domain import db_backend


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _emit_repair_event(
    conn: Any, *,
    claim_id: int, item_id: int,
    prior_blocked_reason: str,
    directional_release: bool,
) -> None:
    try:
        from yoke_core.domain.events import emit_event as _native_emit
    except ImportError:
        return
    session_id = next(
        (os.environ[n] for n in (
            "YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID",
        ) if os.environ.get(n)),
        "",
    )
    try:
        _native_emit(
            "PathClaimCoordinationOnlyRepaired",
            event_kind="lifecycle", event_type="path_claim",
            source_type="system", session_id=session_id,
            severity="INFO", outcome="completed",
            project="yoke", item_id=item_id,
            context={
                "claim_id": claim_id,
                "prior_blocked_reason": prior_blocked_reason,
                "new_state": "planned",
                "directional_release": directional_release,
            },
            conn=conn,
        )
    except Exception:
        return


def _has_upstream_of_blocks_overlap(
    conn: Any,
    *,
    claim_id: int,
    integration_target: str,
    candidate_item_id: int,
) -> bool:
    """Return True when the candidate is the BLOCKER side of a non-coord
    edge to at least one overlapping non-terminal claim.

    The directional-release flip case: the row was authored ``blocked``
    by the pre-directional classifier reading a ``blocks`` edge from
    candidate to other as if it serialized the candidate. The new
    classifier returns ``NONE`` for the same shape, so this predicate
    distinguishes the directional flip from the legacy coord-only flip
    in the emitted ``PathClaimCoordinationOnlyRepaired`` event.
    """
    from yoke_core.domain.path_claims_dependency_resolver import (
        _claim_owning_item,
    )
    from yoke_core.domain.path_claims_dependency_resolver_coordination import (
        has_forward_serial_edge,
    )
    from yoke_core.domain.path_claims_overlap import expand_lineage

    p = _p(conn)
    target_rows = conn.execute(
        f"SELECT target_id FROM path_claim_targets WHERE claim_id = {p}",
        (claim_id,),
    ).fetchall()
    expanded = expand_lineage(conn, [int(t[0]) for t in target_rows])
    if not expanded:
        return False
    placeholders = ",".join(p for _ in expanded)
    overlaps = conn.execute(
        f"SELECT DISTINCT pct.claim_id FROM path_claim_targets pct "
        f"JOIN path_claims pc ON pc.id = pct.claim_id "
        f"WHERE pc.integration_target = {p} "
        f"AND pc.state IN ('planned', 'blocked', 'active') "
        f"AND pc.mode <> 'exception' AND pc.id <> {p} "
        f"AND pct.target_id IN ({placeholders})",
        (integration_target, claim_id, *expanded),
    ).fetchall()
    for (other_id,) in overlaps:
        other_item_id = _claim_owning_item(conn, int(other_id))
        if other_item_id is None:
            continue
        if has_forward_serial_edge(
            conn,
            dependent_item_id=other_item_id,
            blocking_item_id=candidate_item_id,
        ):
            return True
    return False


def repair_coordination_only_blocked(
    conn: Any,
    *,
    item_id: Optional[int] = None,
    actor_id: Optional[int] = None,
) -> List[int]:
    """Reclassify ``state='blocked'`` claims that no longer hold a mutex.

    When ``item_id`` is supplied, only that item's blocked rows are
    inspected (the advance-time call shape). When omitted, every
    ``state='blocked'`` row is considered (the operator recovery shape
    for sweeping the historical cluster). ``actor_id`` narrows the
    advance-time variant further to a single owning actor.

    For each candidate, re-runs
    :func:`yoke_core.domain.path_claims_overlap.classify_overlap` in
    register phase against the live frontier. If the result is
    ``OverlapClassification.NONE`` the claim was held by the legacy
    coord-only mutex; flip it to ``state='planned'`` and clear
    ``blocked_reason``. Any other classification keeps the row blocked.

    Returns the list of claim ids that were repaired.
    """
    from yoke_core.domain.path_claims_overlap import (
        OverlapClassification, classify_overlap,
    )

    where = "state = 'blocked'"
    params: list = []
    p = _p(conn)
    if item_id is not None:
        where += f" AND item_id = {p}"
        params.append(int(item_id))
    if actor_id is not None:
        where += f" AND actor_id = {p}"
        params.append(int(actor_id))
    rows = conn.execute(
        f"SELECT id, item_id, integration_target, blocked_reason "
        f"FROM path_claims WHERE {where} ORDER BY id",
        tuple(params),
    ).fetchall()
    if not rows:
        return []

    repaired: List[int] = []
    for row in rows:
        claim_id = int(row[0])
        owning_item_id = int(row[1]) if row[1] is not None else None
        integration_target = str(row[2])
        prior_reason = str(row[3] or "")
        target_rows = conn.execute(
            f"SELECT target_id FROM path_claim_targets WHERE claim_id = {p}",
            (claim_id,),
        ).fetchall()
        outcome = classify_overlap(
            conn,
            target_ids=[int(t[0]) for t in target_rows],
            integration_target=integration_target,
            upstream_claim_id=None,
            exclude_claim_id=claim_id,
            candidate_item_id=owning_item_id,
            phase="register",
        )
        if outcome is OverlapClassification.NONE:
            directional = (
                owning_item_id is not None
                and _has_upstream_of_blocks_overlap(
                    conn,
                    claim_id=claim_id,
                    integration_target=integration_target,
                    candidate_item_id=owning_item_id,
                )
            )
            conn.execute(
                "UPDATE path_claims SET state = 'planned', "
                f"blocked_reason = NULL WHERE id = {p}",
                (claim_id,),
            )
            repaired.append(claim_id)
            if owning_item_id is not None:
                _emit_repair_event(
                    conn,
                    claim_id=claim_id,
                    item_id=owning_item_id,
                    prior_blocked_reason=prior_reason,
                    directional_release=directional,
                )
    conn.commit()
    return repaired


__all__ = ["repair_coordination_only_blocked"]
