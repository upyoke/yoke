# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import (
    insert_item,
    insert_item_worktree,
    insert_qa_requirement,
    insert_qa_run,
)

from yoke_core.domain.item_merge_receipt_document import record_entry

from yoke_core.domain.backlog_authoritative_status_gate import (
    _run_authoritative_status_gate,
)

from yoke_core.domain.qa_review_waits import QaReviewWait


def _terminal_result(test_db) -> dict:
    return _run_authoritative_status_gate(
        item_id=10,
        target_status="done",
        db_path="",
        qa_bypass=True,
        force=True,
        conn=test_db,
    ) or {"success": True}


def _seed_plan_execution(test_db, *, state: str) -> None:
    test_db.execute(
        "INSERT INTO qa_plan_executions "
        "(id, item_id, transition_id, session_id, roster_digest, roster_json, "
        "cursor_ordinal, state, created_at, heartbeat_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            f"execution-{state}",
            10,
            "reviewing-implementation",
            "session-1",
            "digest",
            "[]",
            0,
            state,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    test_db.commit()


def _seed_merging_sha(test_db, sha: str) -> None:
    lane = insert_item_worktree(test_db, item_id=10, branch="YOK-10")
    lane_id = int(lane["id"] if hasattr(lane, "keys") else lane[0])
    test_db.execute(
        "UPDATE item_worktrees SET commit_sha = %s WHERE id = %s",
        (sha, lane_id),
    )
    test_db.commit()


def _tree_result(sha: str) -> str:
    return '{"verification_tree":{"head_sha":"' + sha + '"}}'
