"""Grade item QA passes against the recorded implementation lane head."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.item_worktrees import primary_item_worktree
from yoke_core.domain.qa_latest_execution import latest_executions
from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.qa_requirement_pass_currency import current_passing_requirements


def candidate_passed_requirements(
    conn: Any, roster: list[dict[str, Any]], *, item_id: int
) -> tuple[str, set[int]]:
    """The candidate commit and the roster requirements already passed there."""
    lane = primary_item_worktree(conn, int(item_id)) or {}
    candidate = str(lane.get("commit_sha") or "").strip()
    if not candidate:
        return "", set()
    current = current_passing_requirements(
        conn, [int(row["requirement_id"]) for row in roster]
    )
    latest = latest_executions(conn, current)
    return candidate, {
        requirement_id
        for requirement_id in current
        if requirement_id in latest
        and recorded_head_sha(latest[requirement_id]["raw_result"]) == candidate
    }
