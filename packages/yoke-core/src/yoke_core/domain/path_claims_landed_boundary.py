"""Identify the landing that describes the item's current work."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.item_landings import ItemLanding, landings_for_item
from yoke_core.domain.item_worktrees import primary_item_worktree
from yoke_core.domain.schema_common import _table_exists


def landing_for_boundary(conn: Any, item_id: int) -> Optional[ItemLanding]:
    """The landing that answers this item's boundary, or ``None`` before one.

    A database that has not converged ``item_landings`` has recorded no
    landing either, so it takes the lane-based check rather than failing.
    """
    if not _table_exists(conn, "item_landings"):
        return None
    landings = landings_for_item(conn, item_id)
    if not landings:
        return None
    newest = landings[-1]
    lane = primary_item_worktree(conn, item_id) or {}
    head = str(lane.get("commit_sha") or "")
    if head and head not in (newest.candidate_sha, newest.merge_sha):
        return None
    return newest
