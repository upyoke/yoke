"""Symlink-aware plumbing for path-claim registration."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from yoke_core.domain import path_claims_events_symlink as _events
from yoke_core.domain.path_claims_symlink_expansion import (
    SYMLINK_CANONICALIZED,
    SymlinkDecision,
    expand_symlinks_from_snapshot_facts,
)
from yoke_core.domain.path_registry import target_at


def expand_for_registration(
    conn: Any,
    project_id: int | str,
    paths,
):
    """Expand the operator's paths from the latest synced snapshot facts.

    Returns ``(path_list, decisions)``. When the project has no usable
    symlink facts or ``paths`` is empty, returns the input paths with an
    empty decisions list. Callers feed ``path_list`` into the downstream
    resolver; ``decisions`` is consumed after the claim id is known via
    :func:`emit_decisions`.
    """
    path_list = [p for p in paths if (p or "").strip()]
    if not path_list:
        return path_list, []
    return expand_symlinks_from_snapshot_facts(conn, project_id, path_list)


def emit_decisions(
    conn: Any,
    *,
    claim_id: int,
    project_id: str,
    item_id: Optional[int],
    session_id: Optional[str],
    decisions: Sequence[SymlinkDecision],
) -> None:
    """Emit per-decision symlink events for a freshly-registered claim."""
    if not decisions:
        return
    cache: Dict[str, Optional[int]] = {}

    def _tid(path_string: str) -> Optional[int]:
        if path_string not in cache:
            cache[path_string] = target_at(conn, project_id, path_string)
        return cache[path_string]

    for decision in decisions:
        sym_id = _tid(decision.symlink_path)
        if decision.reason == SYMLINK_CANONICALIZED and decision.canonical_path:
            _events.emit_symlink_canonicalized(
                conn=conn,
                claim_id=claim_id,
                project=project_id,
                symlink_path=decision.symlink_path,
                canonical_path=decision.canonical_path,
                symlink_target_id=sym_id,
                canonical_target_id=_tid(decision.canonical_path),
                item_id=item_id,
                session_id=session_id,
            )
        else:
            _events.emit_symlink_skipped(
                conn=conn,
                claim_id=claim_id,
                project=project_id,
                symlink_path=decision.symlink_path,
                reason=decision.reason,
                target_attempt=decision.target_attempt,
                symlink_target_id=sym_id,
                item_id=item_id,
                session_id=session_id,
            )


__all__ = ["emit_decisions", "expand_for_registration"]
