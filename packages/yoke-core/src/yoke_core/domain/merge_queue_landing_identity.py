"""Commit observed PR identity with its landing stamps before notifying workers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from yoke_core.domain import db_backend, item_merge_receipt_document
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.engines.merge_worktree_landing_state import PrLandingState


def stamp_landing(
    conn: Any,
    *,
    item_id: int,
    pr_number: str,
    state: PrLandingState,
    landed_at: datetime,
) -> bool:
    """Fold the current PR's receipt into the caller's landing transaction.

    The conditional update locks the item before the receipt fold. A changed
    PR or a competing observer cannot stamp this observation's identity.
    The caller owns commit/rollback and sends the notice only after this write.
    """
    if not (
        state.merged
        and state.head_branch
        and state.target_branch
        and re.fullmatch(r"[0-9a-fA-F]{40}", state.head_sha)
        and re.fullmatch(r"[0-9a-fA-F]{40}", state.merge_commit_sha)
    ):
        raise ValueError(
            "merge_landing_identity_missing: merged PR readback must name its "
            "current head branch, target, head SHA and merge SHA; retry the "
            "landing observation with a complete GitHub PR readback"
        )
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    cursor = conn.execute(
        f"UPDATE items SET merge_queue_landed_at={marker}, merged_at={marker} "
        f"WHERE id={marker} AND merge_queue_pr_number={marker} "
        "AND NULLIF(CAST(merge_queue_landed_at AS TEXT),'') IS NULL",
        (
            instant_parameter(conn, landed_at),
            instant_parameter(conn, landed_at),
            item_id,
            pr_number,
        ),
    )
    if not cursor.rowcount:
        return False
    item_merge_receipt_document.record_entry(
        conn,
        item_id=item_id,
        branch=state.head_branch,
        target=state.target_branch,
        commit_sha=state.head_sha,
        merge_sha=state.merge_commit_sha,
    )
    return True
