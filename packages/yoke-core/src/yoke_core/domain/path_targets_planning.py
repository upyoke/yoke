"""Plan exact future paths through the Canonical Path Registry.

Required Behavior #1 + #7 + Planned-Ancestor Creation Rule from the
path-target materialization contract spec. Lives in its own module so the larger
:mod:`yoke_core.domain.path_targets_materialization` stays focused
on the snapshot-time observation flip; together they replace the
single overgrown file an earlier draft attempted.

``plan_path_target`` accepts an exact ``(project_id, path_string,
kind)`` and an optional attribution ``(item_id, claim_id)`` and
returns the canonical ``path_targets.id``. It walks ancestors leaf to
root, reusing observed/planned rows verbatim, re-planning abandoned
rows in place, and minting fresh planned rows for paths not yet in
the registry. Each newly minted or re-planned row emits
``PathTargetPlanned``.

Pure SQL plus event emission. No git reads, no overlap checks, no
claim insertion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from yoke_core.domain import path_targets_events as _events
from yoke_core.domain.path_project_relative import invalid_project_relative_paths
from yoke_core.domain.path_registry import (
    KIND_DIRECTORY,
    KIND_FILE,
    _parent_path_string,
)
from yoke_core.domain.path_targets_states import (
    ABANDONED as _ABANDONED,
    OBSERVED as _OBSERVED,
    PLANNED as _PLANNED,
    TENTATIVE as _TENTATIVE,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ancestor_chain_paths(path_string: str) -> List[str]:
    chain: List[str] = []
    parent = _parent_path_string(path_string)
    while parent is not None:
        chain.append(parent)
        parent = _parent_path_string(parent)
    return chain


def _latest_target_row(
    conn: Any, project_id: int, path_string: str,
) -> Optional[Tuple[int, str, int, Optional[int], str]]:
    row = conn.execute(
        "SELECT id, kind, generation, parent_target_id, materialization_state "
        "FROM path_targets "
        "WHERE project_id = %s AND path_string = %s "
        "ORDER BY generation DESC LIMIT 1",
        (project_id, path_string),
    ).fetchone()
    if row is None:
        return None
    parent = None if row[3] is None else int(row[3])
    return int(row[0]), str(row[1]), int(row[2]), parent, str(row[4])


def _mint_pre_observation_row(
    conn: Any,
    *,
    project_id: int,
    path_string: str,
    kind: str,
    parent_target_id: Optional[int],
    item_id: Optional[int],
    claim_id: Optional[int],
    generation: int,
    now_iso: str,
    state: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO path_targets ("
        "  project_id, kind, path_string, generation, parent_target_id, "
        "  created_at, materialization_state, materialization_updated_at, "
        "  planned_by_item_id, planned_by_claim_id"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            project_id, kind, path_string, generation, parent_target_id,
            now_iso, state, now_iso, item_id, claim_id,
        ),
    )
    return int(cur.fetchone()[0])


def _re_plan_row(
    conn: Any,
    *,
    target_id: int,
    item_id: Optional[int],
    claim_id: Optional[int],
    now_iso: str,
    state: str,
) -> None:
    conn.execute(
        "UPDATE path_targets "
        "SET materialization_state = %s, "
        "    materialization_updated_at = %s, "
        "    planned_by_item_id = COALESCE(planned_by_item_id, %s), "
        "    planned_by_claim_id = COALESCE(planned_by_claim_id, %s) "
        "WHERE id = %s",
        (state, now_iso, item_id, claim_id, target_id),
    )


def _attribution_backfill(
    conn: Any,
    *,
    target_id: int,
    item_id: Optional[int],
    claim_id: Optional[int],
) -> None:
    if item_id is None and claim_id is None:
        return
    conn.execute(
        "UPDATE path_targets "
        "SET planned_by_item_id = COALESCE(planned_by_item_id, %s), "
        "    planned_by_claim_id = COALESCE(planned_by_claim_id, %s) "
        "WHERE id = %s",
        (item_id, claim_id, target_id),
    )


def _resolve_or_plan_single(
    conn: Any,
    *,
    project_id: int,
    path_string: str,
    kind: str,
    parent_target_id: Optional[int],
    item_id: Optional[int],
    claim_id: Optional[int],
    session_id: Optional[str],
    now_iso: str,
    target_state: str = _PLANNED,
) -> int:
    latest = _latest_target_row(conn, project_id, path_string)
    if latest is not None:
        target_id, latest_kind, generation, latest_parent, state = latest
        if state == _OBSERVED:
            return target_id
        if state == _PLANNED:
            _attribution_backfill(
                conn, target_id=target_id,
                item_id=item_id, claim_id=claim_id,
            )
            return target_id
        if state == _TENTATIVE:
            _attribution_backfill(
                conn, target_id=target_id,
                item_id=item_id, claim_id=claim_id,
            )
            return target_id
        if state == _ABANDONED:
            _re_plan_row(
                conn, target_id=target_id,
                item_id=item_id, claim_id=claim_id, now_iso=now_iso,
                state=target_state,
            )
            _events.emit_pre_observation(
                conn=conn, target_id=target_id, project_id=project_id,
                path_string=path_string, kind=latest_kind,
                generation=generation, parent_target_id=latest_parent,
                item_id=item_id, claim_id=claim_id,
                old_state=_ABANDONED, new_state=target_state,
                session_id=session_id,
            )
            return target_id
    new_id = _mint_pre_observation_row(
        conn, project_id=project_id, path_string=path_string, kind=kind,
        parent_target_id=parent_target_id, item_id=item_id,
        claim_id=claim_id, generation=1, now_iso=now_iso,
        state=target_state,
    )
    _events.emit_pre_observation(
        conn=conn, target_id=new_id, project_id=project_id,
        path_string=path_string, kind=kind, generation=1,
        parent_target_id=parent_target_id, item_id=item_id,
        claim_id=claim_id, old_state=None, new_state=target_state,
        session_id=session_id,
    )
    return new_id


def _ensure_ancestor_chain(
    conn: Any,
    *,
    project_id: int,
    path_string: str,
    item_id: Optional[int],
    claim_id: Optional[int],
    session_id: Optional[str],
    now_iso: str,
) -> Optional[int]:
    ancestors = _ancestor_chain_paths(path_string)
    if not ancestors:
        return None
    immediate_parent = ancestors[0]
    grandparent_id: Optional[int] = None
    for anc_path in reversed(ancestors):
        anc_id = _resolve_or_plan_single(
            conn, project_id=project_id, path_string=anc_path,
            kind=KIND_DIRECTORY, parent_target_id=grandparent_id,
            item_id=item_id, claim_id=claim_id,
            session_id=session_id, now_iso=now_iso,
        )
        if anc_path == immediate_parent:
            return anc_id
        grandparent_id = anc_id
    return None  # pragma: no cover — loop always returns above


def plan_path_target(
    conn: Any,
    *,
    project_id: int,
    path_string: str,
    kind: str,
    item_id: Optional[int] = None,
    claim_id: Optional[int] = None,
    session_id: Optional[str] = None,
) -> int:
    """Resolve or mint a planned ``path_targets`` row for an exact path.

    See module docstring for the full identity/state policy. Raises
    ``ValueError`` for kinds other than ``file`` / ``directory``.
    """
    return _plan_with_state(
        conn,
        project_id=project_id,
        path_string=path_string,
        kind=kind,
        item_id=item_id,
        claim_id=claim_id,
        session_id=session_id,
        target_state=_PLANNED,
    )


def plan_tentative_path_target(
    conn: Any,
    *,
    project_id: int,
    path_string: str,
    kind: str,
    item_id: Optional[int] = None,
    claim_id: Optional[int] = None,
    session_id: Optional[str] = None,
) -> int:
    """Resolve or mint a tentative ``path_targets`` row for an exact path.

    Tentative coverage is the operator's "I might touch this" — a
    weaker reservation than ``planned``. The path participates in
    overlap detection and renders distinctly, but its absence from the
    eventual implementation is not a missed promise. Existing observed
    or planned rows are reused verbatim (planned is a stronger claim
    and is never downgraded). Existing tentative rows backfill
    attribution. Existing abandoned rows re-plan as tentative.
    """
    return _plan_with_state(
        conn,
        project_id=project_id,
        path_string=path_string,
        kind=kind,
        item_id=item_id,
        claim_id=claim_id,
        session_id=session_id,
        target_state=_TENTATIVE,
    )


def _plan_with_state(
    conn: Any,
    *,
    project_id: int,
    path_string: str,
    kind: str,
    item_id: Optional[int],
    claim_id: Optional[int],
    session_id: Optional[str],
    target_state: str,
) -> int:
    if kind not in (KIND_FILE, KIND_DIRECTORY):
        raise ValueError(
            f"plan_path_target: kind must be 'file' or 'directory', got {kind!r}"
        )
    invalid = invalid_project_relative_paths([path_string])
    if invalid:
        raise ValueError(
            "plan_path_target: path_string must be project-relative, "
            f"got {path_string!r}"
        )
    now_iso = _utc_now_iso()
    parent_target_id = _ensure_ancestor_chain(
        conn, project_id=project_id, path_string=path_string,
        item_id=item_id, claim_id=claim_id,
        session_id=session_id, now_iso=now_iso,
    )
    return _resolve_or_plan_single(
        conn, project_id=project_id, path_string=path_string, kind=kind,
        parent_target_id=parent_target_id, item_id=item_id,
        claim_id=claim_id, session_id=session_id, now_iso=now_iso,
        target_state=target_state,
    )


__all__ = ["plan_path_target", "plan_tentative_path_target"]
