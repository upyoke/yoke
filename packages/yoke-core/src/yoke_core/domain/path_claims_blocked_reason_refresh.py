"""Refresh ``path_claims.blocked_reason`` wording when item-dep edges change.

Sibling helper of :mod:`path_claims_dependency_propagation`. The existing
``_refresh_blocked_reason`` only fires from the upstream-release
propagation path; it never re-evaluates wording when the
``item_dependencies`` row that motivated the original block is later
demoted (e.g. ``activation`` -> ``coordination_only``) or removed
entirely. That gap leaves diagnostic text stale: a row authored as
``serial-via-dependency on path_claims.id=N`` keeps that wording even
after the matching dependency edge has been demoted to
``coordination_only`` or removed, misleading operators who read the
claim row to diagnose why a candidate is still blocked.

This helper closes the gap with a wording-only refresh:

* state stays ``blocked`` (state repair for genuinely-not-mutex'd rows
  lives in ``repair_coordination_only_blocked``),
* INSERT / UPDATE / DELETE on ``item_dependencies`` between a pair of
  items triggers a recompute of every non-terminal blocked claim whose
  upstream pointer references a claim owned by either party,
* the new wording reflects the *current* edge shape:
  ``serial-via-dependency on path_claims.id=X`` when a forward serial
  edge survives, ``path-mutex on path_claims.id=X`` when only a path
  mutex survives, and ``path-mutex serialization only`` when neither
  remain, and
* a ``PathClaimBlockedReasonRefreshed`` event fires per refresh with
  ``cause='item_dependency_edge_change'`` plus the affected pair so
  ouroboros distinguishes this trigger from the upstream-release
  refresh path.

The refresh-vs-state-flip split mirrors :mod:`db_mutation_gate_overlap`'s
two-axes pattern: this helper owns the wording axis, while
``repair_coordination_only_blocked`` owns the state axis.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional

from yoke_core.domain import db_backend


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _event_session_id() -> str:
    for name in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _emit_refresh_event(
    conn: Any,
    *,
    claim_id: int,
    item_id: Optional[int],
    prior_blocked_reason: str,
    new_blocked_reason: str,
    dependent_item_id: int,
    blocking_item_id: int,
) -> None:
    try:
        from yoke_core.domain.events import emit_event as _native_emit
    except ImportError:
        return
    try:
        _native_emit(
            "PathClaimBlockedReasonRefreshed",
            event_kind="lifecycle",
            event_type="path_claim",
            source_type="system",
            session_id=_event_session_id(),
            severity="INFO",
            outcome="completed",
            project="yoke",
            item_id=item_id,
            context={
                "claim_id": claim_id,
                "prior_blocked_reason": prior_blocked_reason,
                "new_blocked_reason": new_blocked_reason,
                "cause": "item_dependency_edge_change",
                "dependent_item_id": dependent_item_id,
                "blocking_item_id": blocking_item_id,
            },
            conn=conn,
        )
    except Exception:
        return


def _find_blocking_peer(
    conn: Any,
    *,
    claim_id: int,
    integration_target: str,
    candidate_item_id: Optional[int],
    target_edge,
) -> Optional[int]:
    """Return the first surviving overlap whose dep-edge matches ``target_edge``.

    ``target_edge`` is a :class:`CoordinationClassification` value; the
    helper iterates overlaps in ``claim_id`` order and returns the first
    one whose edge classification matches. Used to pick the peer the
    refreshed ``blocked_reason`` should point at: for
    ``HAS_SERIAL`` (serial-via-dependency wording) the first overlap
    with a forward serial edge; for ``NO_EDGE`` (path-mutex wording)
    the first overlap that genuinely makes the candidate incompatible.
    """
    from yoke_core.domain.path_claims_dependency_resolver_coordination import (
        classify_inter_item_edges,
    )
    from yoke_core.domain.path_claims_overlap import expand_lineage

    p = _p(conn)
    rows = conn.execute(
        f"SELECT target_id FROM path_claim_targets WHERE claim_id = {p}",
        (claim_id,),
    ).fetchall()
    expanded = expand_lineage(conn, [int(t[0]) for t in rows])
    if not expanded:
        return None
    placeholders = ",".join(p for _ in expanded)
    candidates = conn.execute(
        f"SELECT DISTINCT pct.claim_id FROM path_claim_targets pct "
        f"JOIN path_claims pc ON pc.id = pct.claim_id "
        f"WHERE pc.integration_target = {p} "
        f"AND pc.state IN ('planned', 'blocked', 'active') "
        f"AND pc.mode <> 'exception' AND pc.id <> {p} "
        f"AND pct.target_id IN ({placeholders}) "
        f"ORDER BY pct.claim_id",
        (integration_target, claim_id, *expanded),
    ).fetchall()
    for (cid,) in candidates:
        edge = classify_inter_item_edges(
            conn,
            candidate_claim_id=claim_id,
            candidate_item_id=candidate_item_id,
            blocking_claim_id=int(cid),
        )
        if edge is target_edge:
            return int(cid)
    return None


def _compute_new_reason(
    conn: Any,
    *,
    claim_id: int,
    integration_target: str,
    classification,
    candidate_item_id: Optional[int],
) -> str:
    from yoke_core.domain.path_claims_dependency_resolver_coordination import (
        CoordinationClassification,
    )
    from yoke_core.domain.path_claims_overlap import OverlapClassification

    if classification is OverlapClassification.SERIAL_VIA_DEPENDENCY:
        serial_id = _find_blocking_peer(
            conn,
            claim_id=claim_id,
            integration_target=integration_target,
            candidate_item_id=candidate_item_id,
            target_edge=CoordinationClassification.HAS_SERIAL,
        )
        if serial_id is not None:
            return f"serial-via-dependency on path_claims.id={serial_id}"
    elif classification is OverlapClassification.INCOMPATIBLE:
        incompat_id = _find_blocking_peer(
            conn,
            claim_id=claim_id,
            integration_target=integration_target,
            candidate_item_id=candidate_item_id,
            target_edge=CoordinationClassification.NO_EDGE,
        )
        if incompat_id is not None:
            return f"path-mutex on path_claims.id={incompat_id}"
    return "path-mutex serialization only"


def refresh_blocked_reason_for_edge_change(
    conn: Any,
    *,
    dependent_item_id: int,
    blocking_item_id: int,
) -> List[int]:
    """Recompute ``blocked_reason`` for the affected pair. Wording-only.

    Walks every non-terminal ``state='blocked'`` row whose
    ``_blocked_reason_claim_id`` resolves to a claim owned by either
    ``dependent_item_id`` or ``blocking_item_id``. For each candidate,
    re-runs :func:`classify_overlap` in register phase. ``NONE`` is
    skipped (state repair belongs to the coord-only repair pass).
    ``SERIAL_VIA_DEPENDENCY`` and ``INCOMPATIBLE`` are rewritten to
    reflect the current edge shape (serial-via-dependency on a surviving
    serial edge, path-mutex on a surviving overlap without one, or the
    no-claim-id wording when no overlap survives).

    Returns the list of claim ids whose ``blocked_reason`` was rewritten.
    Idempotent: when the recomputed wording matches the prior wording
    the row is left untouched and no event is emitted.
    """
    from yoke_core.domain.path_claims_dependency_propagation import (
        _blocked_reason_claim_id,
        _claim_owning_item,
    )
    from yoke_core.domain.path_claims_overlap import (
        OverlapClassification,
        classify_overlap,
    )

    affected_pair = {int(dependent_item_id), int(blocking_item_id)}
    try:
        rows = conn.execute(
            "SELECT id, blocked_reason, integration_target, item_id "
            "FROM path_claims WHERE state = 'blocked' ORDER BY id"
        ).fetchall()
    except db_backend.operational_error_types(conn):
        # Caller's schema does not provision path_claims (e.g. a minimal
        # in-memory fixture testing dependency-edge writes in isolation).
        # No blocked rows means nothing to refresh.
        return []

    refreshed: List[int] = []
    for row in rows:
        claim_id = int(row[0])
        prior = str(row[1] or "")
        integration_target = str(row[2] or "")
        candidate_item_id = int(row[3]) if row[3] is not None else None

        upstream_id = _blocked_reason_claim_id(prior)
        if upstream_id is None:
            continue
        upstream_item_id = _claim_owning_item(conn, upstream_id)
        if upstream_item_id is None or upstream_item_id not in affected_pair:
            continue

        p = _p(conn)
        target_rows = conn.execute(
            f"SELECT target_id FROM path_claim_targets WHERE claim_id = {p}",
            (claim_id,),
        ).fetchall()
        target_ids = [int(t[0]) for t in target_rows]
        classification = classify_overlap(
            conn,
            target_ids=target_ids,
            integration_target=integration_target,
            upstream_claim_id=None,
            exclude_claim_id=claim_id,
            candidate_item_id=candidate_item_id,
            phase="register",
        )
        if classification is OverlapClassification.NONE:
            continue

        new_reason = _compute_new_reason(
            conn,
            claim_id=claim_id,
            integration_target=integration_target,
            classification=classification,
            candidate_item_id=candidate_item_id,
        )
        if new_reason == prior:
            continue
        conn.execute(
            f"UPDATE path_claims SET blocked_reason = {p} WHERE id = {p}",
            (new_reason, claim_id),
        )
        refreshed.append(claim_id)
        _emit_refresh_event(
            conn,
            claim_id=claim_id,
            item_id=candidate_item_id,
            prior_blocked_reason=prior,
            new_blocked_reason=new_reason,
            dependent_item_id=int(dependent_item_id),
            blocking_item_id=int(blocking_item_id),
        )
    if refreshed:
        conn.commit()
    return refreshed


__all__ = ["refresh_blocked_reason_for_edge_change"]
