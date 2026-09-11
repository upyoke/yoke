"""Refuse deletions that would destroy another item's live worktree.

Scratch cleanup reaps directories once their owning session/process is
verifiably gone (see :mod:`yoke_core.domain.scratch_auto_prune`). That
liveness check answers "is anything still using this scratch tree?" — an
orthogonal question from "does this scratch tree contain something someone
else owns?". A scratch clone mis-registered as a project's checkout can end
up as the ancestor directory of another item's live worktree (the incident
this module exists to stop from repeating); by the time the owning
scratch-clone session ends, that worktree is still active and belongs to
nobody the liveness check would protect.

``item_worktrees.path`` is the durable registry of live lanes regardless of
which session created them, so this checks that registry directly rather
than session/process liveness.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from yoke_core.domain.lint_session_cwd_path_authority import is_inside
from yoke_core.domain.schema_common import _table_exists


def active_worktree_state(conn: Any) -> tuple[list[str], str]:
    """Return every currently active worktree path, plus a registry-read error.

    Mirrors the ``(states..., registry_error)`` shape
    :func:`yoke_core.domain.scratch_auto_prune._session_states` already uses
    for session liveness. An empty error string means the read succeeded —
    including the legitimate case where ``item_worktrees`` does not exist at
    all: a fixture or generic-SQLite validation boundary with no lane table
    has no active worktrees to protect, by construction. A non-empty error
    means the table exists but the registry could not be read, or the
    connection cannot even answer the existence probe — a real read failure,
    not silence — and callers must fail closed rather than treat that the
    same as "nothing is registered".
    """
    try:
        table_present = _table_exists(conn, "item_worktrees")
    except Exception as exc:  # noqa: BLE001 - the existence probe itself failed
        return [], f"item_worktrees existence check failed: {exc}"
    if not table_present:
        return [], ""
    try:
        rows = conn.execute(
            "SELECT path FROM item_worktrees "
            "WHERE state = 'active' AND path IS NOT NULL"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 - fail closed: a real read failure
        return [], f"item_worktrees registry read failed: {exc}"
    paths: list[str] = []
    for row in rows:
        raw = row["path"] if hasattr(row, "keys") else row[0]
        worktree_path = str(raw or "").strip()
        if worktree_path:
            paths.append(worktree_path)
    return paths, ""


def active_worktree_conflict(paths: Iterable[str], candidate: str) -> Optional[str]:
    """Return the active worktree path ``candidate`` is or contains, if any.

    Both sides are compared through :func:`is_inside`, which resolves
    symlinks and canonicalizes each path, so a candidate reaching a live
    worktree via a symlink alias or an ancestor directory is caught the same
    as an exact match. ``paths`` is the registry already read by
    :func:`active_worktree_state` — this half never touches the connection,
    so a caller checking many candidates in one run (``scratch_auto_prune``)
    reads the registry once instead of re-querying it per candidate.
    """
    if not candidate or not candidate.strip():
        return None
    for worktree_path in paths:
        if worktree_path and is_inside(worktree_path, candidate):
            return worktree_path
    return None


__all__ = ["active_worktree_conflict", "active_worktree_state"]
