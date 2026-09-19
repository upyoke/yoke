"""Whether a recorded lane head still describes work, or is a stale pointer.

Completion asks one narrow question beyond delivery: is there a NEWER head on
this item's own lane that the release does not carry? It asks it of
``item_worktrees.commit_sha``, which is a pointer the lane keeps current — and
a rebase rewrites the lane, so the commit that pointer named stops existing
anywhere. Nothing published it, nothing can fetch it, and no source can place
it in any candidate.

Read literally that is "containment undetermined", and the gate refuses. But
the item merged: whatever the lane held reached the base under the commit that
actually landed, which the release does carry. So the honest reading of an
unplaceable head beside a contained merge is not "undeployed work" — it is a
pointer a rebase orphaned, and the work it used to name is shipped.

This is deliberately narrow. An unplaceable head whose merge is NOT contained
stays a refusal, because then nothing has established that the lane's work
shipped at all.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.delivery_evidence_ladder import item_merge_identity
from yoke_core.domain.deployment_run_candidate_containment import (
    candidate_contains_commit,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


def active_lane_head(conn: Any, item_id: int) -> str:
    """The commit the item's active lane last recorded, or ``""``."""
    if not (
        _table_exists(conn, "item_worktrees")
        and _column_exists(conn, "item_worktrees", "commit_sha")
    ):
        return ""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT commit_sha FROM item_worktrees "
        f"WHERE item_id = {marker} AND state = 'active' "
        "AND commit_sha IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return ""
    value = row["commit_sha"] if hasattr(row, "keys") else row[0]
    return str(value or "").strip()


def recorded_merge_identity(conn: Any, item_id: int, evidence_merge_sha: str) -> str:
    """The merge this item landed, from the same place its gate reads it.

    The caller's own evidence record comes first: resolving the identity a
    second way is how a check ends up answering about a different commit
    than the gate it is qualifying.
    """
    return str(evidence_merge_sha or "").strip() or item_merge_identity(
        conn, int(item_id)
    )


def head_is_stale_bookkeeping(
    conn: Any,
    *,
    item_id: int,
    project_id: int,
    lineage: str,
    merge_sha: str = "",
) -> bool:
    """Whether an unplaceable lane head is an orphaned pointer, not new work.

    Only asked once the head's own containment came back undetermined, so
    this decides between the two readings of that one answer rather than
    softening a definite exclusion.
    """
    merge_sha = recorded_merge_identity(conn, int(item_id), merge_sha)
    if not merge_sha or not lineage:
        return False
    return candidate_contains_commit(
        conn,
        int(project_id),
        candidate_lineage=lineage,
        commit_sha=merge_sha,
    ).contained


__all__ = [
    "active_lane_head",
    "head_is_stale_bookkeeping",
    "recorded_merge_identity",
]
