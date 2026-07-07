"""Snapshot-time materialization of planned/tentative path_targets rows.

Required Behavior #3 from the path-target materialization contract spec. Sister of
:mod:`yoke_core.domain.path_targets_planning`, which mints planned
or tentative rows on the claim/refine path; this module owns the
``planned/tentative → observed`` flip the snapshot scanner triggers
when git later observes a path whose latest target is still in a
pre-observation state.

Two helpers:

* :func:`find_planned_match` — the scanner's pre-mint check. Returns
  the existing target id when ``(project, path, kind, parent)`` matches
  exactly and the latest row is in a pre-observation state
  (``planned`` or ``tentative``), so the scanner reuses the existing
  identity rather than minting a parallel target row.
* :func:`materialize_planned_target` — flips the row to observed and
  emits ``PathTargetMaterialized``. Idempotent: returns ``False`` when
  the row was already observed or missing. Promotes both ``planned``
  and ``tentative`` rows.

Re-exported here so existing call sites (and the spec's
documented surface) keep working: :func:`plan_path_target` and
:func:`plan_tentative_path_target` are imported from the planning
module so callers can stay on a single import path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain import path_targets_events as _events
from yoke_core.domain.path_targets_planning import (
    plan_path_target,
    plan_tentative_path_target,
)
from yoke_core.domain.path_targets_states import (
    PRE_OBSERVATION_STATES as _PRE_OBSERVATION_STATES,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def find_planned_match(
    conn: Any,
    *,
    project_id: int,
    path_string: str,
    kind: str,
    parent_target_id: Optional[int],
) -> Optional[int]:
    """Return the pre-observation ``path_targets.id`` matching observation params.

    Only returns the latest-generation row's id when its
    ``(kind, parent_target_id)`` matches the snapshot scanner's
    about-to-mint observation and the row is currently in a
    pre-observation state (``planned`` or ``tentative``). Tentative
    rows ride the same materialization path as planned — the scanner
    promotes them to ``observed`` instead of minting a parallel row.
    """
    p = _p(conn)
    row = conn.execute(
        "SELECT id, kind, parent_target_id, materialization_state "
        "FROM path_targets "
        f"WHERE project_id = {p} AND path_string = {p} "
        "ORDER BY generation DESC LIMIT 1",
        (project_id, path_string),
    ).fetchone()
    if row is None:
        return None
    if str(row[3]) not in _PRE_OBSERVATION_STATES or str(row[1]) != kind:
        return None
    existing_parent = None if row[2] is None else int(row[2])
    if existing_parent != parent_target_id:
        return None
    return int(row[0])


def materialize_planned_target(
    conn: Any,
    *,
    target_id: int,
    commit_sha: str,
    session_id: Optional[str] = None,
) -> bool:
    """Flip a planned/tentative target to observed.

    Emits ``PathTargetMaterialized``. Returns ``True`` when the row
    was actually flipped (state was ``planned`` or ``tentative`` going
    in), ``False`` when the row was already observed or has no
    matching id. The snapshot scanner uses the return value to decide
    whether to emit the materialized event.
    """
    p = _p(conn)
    row = conn.execute(
        "SELECT id, project_id, path_string, kind, generation, "
        "       parent_target_id, materialization_state, "
        "       planned_by_item_id, planned_by_claim_id "
        f"FROM path_targets WHERE id = {p}",
        (target_id,),
    ).fetchone()
    if row is None or str(row[6]) not in _PRE_OBSERVATION_STATES:
        return False
    now_iso = _utc_now_iso()
    conn.execute(
        "UPDATE path_targets "
        "SET materialization_state = 'observed', "
        f"    materialization_updated_at = {p} "
        f"WHERE id = {p}",
        (now_iso, target_id),
    )
    _events.emit_materialized(
        conn=conn,
        target_id=int(row[0]),
        project_id=str(row[1]),
        path_string=str(row[2]),
        kind=str(row[3]),
        generation=int(row[4]),
        parent_target_id=None if row[5] is None else int(row[5]),
        commit_sha=commit_sha,
        item_id=None if row[7] is None else int(row[7]),
        claim_id=None if row[8] is None else int(row[8]),
        session_id=session_id,
    )
    return True


def abandon_planned_target(
    conn: Any,
    *,
    target_id: int,
    reason: str,
    session_id: Optional[str] = None,
) -> bool:
    """Flip a planned/tentative target to abandoned.

    Emits ``PathTargetAbandoned``. Returns ``True`` when the row was
    actually flipped (state was ``planned`` or ``tentative`` going
    in), ``False`` when the row was already abandoned, observed, or
    missing. Used by claim cancel / amendment-narrow paths so
    abandoned pre-observation targets surface in invariants and
    operator-facing reads. Tentative-then-abandoned describes the
    operator-correct outcome ("predicted touch did not happen") with
    the same state transition and event shape as planned-then-
    abandoned; downstream consumers distinguish via the prior state
    on the abandonment event payload.
    """
    p = _p(conn)
    row = conn.execute(
        "SELECT id, project_id, path_string, kind, generation, "
        "       parent_target_id, materialization_state, "
        "       planned_by_item_id, planned_by_claim_id "
        f"FROM path_targets WHERE id = {p}",
        (target_id,),
    ).fetchone()
    if row is None or str(row[6]) not in _PRE_OBSERVATION_STATES:
        return False
    now_iso = _utc_now_iso()
    conn.execute(
        "UPDATE path_targets "
        "SET materialization_state = 'abandoned', "
        f"    materialization_updated_at = {p} "
        f"WHERE id = {p}",
        (now_iso, target_id),
    )
    _events.emit_abandoned(
        conn=conn,
        target_id=int(row[0]),
        project_id=str(row[1]),
        path_string=str(row[2]),
        kind=str(row[3]),
        generation=int(row[4]),
        parent_target_id=None if row[5] is None else int(row[5]),
        reason=reason,
        item_id=None if row[7] is None else int(row[7]),
        claim_id=None if row[8] is None else int(row[8]),
        session_id=session_id,
    )
    return True


def abandon_planned_targets_without_open_claim(
    conn: Any,
    *,
    target_ids: Iterable[int],
    reason: str,
    session_id: Optional[str] = None,
) -> int:
    """Abandon planned/tentative targets no non-terminal claim still covers."""
    ids = [int(t) for t in target_ids]
    if not ids:
        return 0
    abandoned = 0
    for target_id in ids:
        p = _p(conn)
        row = conn.execute(
            f"SELECT materialization_state FROM path_targets WHERE id = {p}",
            (target_id,),
        ).fetchone()
        if row is None or str(row[0]) not in _PRE_OBSERVATION_STATES:
            continue
        still_claimed = conn.execute(
            "SELECT 1 FROM path_claim_targets pct "
            "JOIN path_claims pc ON pc.id = pct.claim_id "
            f"WHERE pct.target_id = {p} "
            "AND pc.state IN ('planned', 'blocked', 'active') "
            "LIMIT 1",
            (target_id,),
        ).fetchone()
        if still_claimed is not None:
            continue
        if abandon_planned_target(
            conn, target_id=target_id, reason=reason,
            session_id=session_id,
        ):
            abandoned += 1
    return abandoned


__all__ = [
    "abandon_planned_target",
    "abandon_planned_targets_without_open_claim",
    "find_planned_match",
    "materialize_planned_target",
    "plan_path_target",
    "plan_tentative_path_target",
]
