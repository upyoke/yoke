"""Committed-head persistence for active item worktree lanes."""

from __future__ import annotations

import re
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now

_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40,64}$")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def record_head_for_checkout(
    conn: Any,
    *,
    project_id: int,
    checkout_path: str,
    commit_sha: str,
) -> Optional[int]:
    """Bind an active lane at ``checkout_path`` to its just-committed HEAD.

    The global post-commit snapshot already proves the checkout path and
    commit identity locally. Matching both project and active lane path keeps
    ordinary commits outside a registered lane as a no-op.
    """
    clean_path = str(checkout_path).strip()
    clean_sha = str(commit_sha).strip()
    if not clean_path:
        raise ValueError("checkout_path is required")
    if not _COMMIT_SHA.fullmatch(clean_sha):
        raise ValueError("commit_sha must be a full git commit identity")
    marker = _p(conn)
    row = conn.execute(
        "SELECT iw.id FROM item_worktrees iw "
        "JOIN items i ON i.id = iw.item_id "
        f"WHERE i.project_id = {marker} AND iw.path = {marker} "
        "AND iw.state = 'active'",
        (int(project_id), clean_path),
    ).fetchone()
    if row is None:
        return None
    lane_id = int(row[0])
    conn.execute(
        "UPDATE item_worktrees "
        f"SET commit_sha = {marker}, updated_at = {marker} "
        f"WHERE id = {marker}",
        (clean_sha, iso8601_now(), lane_id),
    )
    return lane_id


__all__ = ["record_head_for_checkout"]
