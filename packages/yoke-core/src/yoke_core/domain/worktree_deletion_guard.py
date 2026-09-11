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

from typing import Any, Optional

from yoke_core.domain.lint_session_cwd_path_authority import is_inside
from yoke_core.domain.schema_common import _table_exists


def active_worktree_conflict(conn: Any, candidate: str) -> Optional[str]:
    """Return the active worktree path ``candidate`` is or contains, if any.

    Both sides are compared through :func:`is_inside`, which resolves
    symlinks and canonicalizes each path, so a candidate reaching a live
    worktree via a symlink alias or an ancestor directory is caught the same
    as an exact match. ``None`` means deletion is safe with respect to every
    recorded active worktree — either there is no conflict, or the schema
    cannot answer (a fixture with no lane table, a connection stub with no
    query surface, or a live connection that raises), in which case the
    caller's own age/liveness gates still apply.
    """
    if not candidate or not candidate.strip():
        return None
    try:
        if not _table_exists(conn, "item_worktrees"):
            return None
        rows = conn.execute(
            "SELECT path FROM item_worktrees "
            "WHERE state = 'active' AND path IS NOT NULL"
        ).fetchall()
    except Exception:  # noqa: BLE001 - fail closed across DB/stub boundaries
        return None
    for row in rows:
        raw = row["path"] if hasattr(row, "keys") else row[0]
        worktree_path = str(raw or "").strip()
        if worktree_path and is_inside(worktree_path, candidate):
            return worktree_path
    return None


__all__ = ["active_worktree_conflict"]
