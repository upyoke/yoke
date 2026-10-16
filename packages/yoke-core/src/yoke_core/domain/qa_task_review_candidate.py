"""Validate the exact worker candidate a task review judged."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Any

from yoke_core.domain.db_helpers import connect, query_one

RECOVERY = (
    "Review the current committed task candidate, then retry review-insert "
    "with its full --head-sha. If the registered task lane/head is stale, "
    "ask the control-plane operator to repair its normal post-commit snapshot."
)


def prepare_task_review_run(arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate the Epic review bridge before ordinary commit-bound recording."""
    if (
        arguments.get("qa_kind") != "implementation_review"
        or arguments.get("verdict") != "pass"
    ):
        return arguments
    with connect(path=arguments.get("db_path")) as conn:
        requirement = query_one(
            conn,
            "SELECT epic_id,task_num FROM qa_requirements WHERE id=%s",
            (arguments["requirement_id"],),
        )
        if (
            not requirement
            or requirement["epic_id"] is None
            or requirement["task_num"] is None
        ):
            return arguments
        raw, refusal = bind_task_review_candidate(
            conn,
            requirement,
            arguments.get("raw_result"),
            arguments.get("head_sha"),
        )
    if refusal:
        print("Error: " + refusal, file=sys.stderr)
        raise SystemExit(2)
    return {**arguments, "raw_result": raw}


def bind_task_review_candidate(
    conn: Any,
    requirement: dict[str, Any],
    raw_result: str | None,
    head_sha: str | None,
) -> tuple[str | None, str]:
    """Bind only a matching active worker lane owned by this review's epic."""
    from yoke_core.domain.qa_run_commit_binding import _git, wrap_evidence

    expected = str(head_sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", expected):
        return raw_result, "task_review_candidate_required: " + RECOVERY
    lane = query_one(
        conn,
        "SELECT w.item_id,w.lane_role,w.state,w.path,w.branch,w.commit_sha "
        "FROM epic_tasks t LEFT JOIN item_worktrees w ON w.id=t.item_worktree_id "
        "WHERE t.epic_id=%s AND t.task_num=%s",
        (int(requirement["epic_id"]), int(requirement["task_num"])),
    )
    if (
        not lane
        or lane["item_id"] != int(requirement["epic_id"])
        or lane["lane_role"] != "worker"
        or lane["state"] != "active"
    ):
        return raw_result, "task_review_lane_invalid: " + RECOVERY
    recorded = str(lane["commit_sha"] or "").strip().lower()
    if expected != recorded:
        return raw_result, (
            f"task_review_candidate_mismatch: reviewed {expected}; "
            f"registered task candidate {recorded or '<missing>'}. " + RECOVERY
        )
    root = str(lane["path"] or "").strip()
    if not root:
        return (
            raw_result,
            "task_review_lane_invalid: registered path missing. " + RECOVERY,
        )
    if os.path.isdir(root):
        actual_root = _git(root, "rev-parse", "--show-toplevel")
        branch = _git(root, "branch", "--show-current")
        head = _git(root, "rev-parse", "HEAD")
        if (
            not actual_root
            or os.path.realpath(actual_root) != os.path.realpath(root)
            or branch != lane["branch"]
            or head != expected
        ):
            return raw_result, "task_review_checkout_mismatch: " + RECOVERY
        # An empty status is valid; an unreadable checkout must refuse.
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return raw_result, "task_review_checkout_unreadable: " + RECOVERY
        if status.returncode:
            return raw_result, "task_review_checkout_unreadable: " + RECOVERY
        if status.stdout.strip():
            return (
                raw_result,
                "task_review_dirty_tree: commit the task changes and review again. "
                + RECOVERY,
            )
    # Hosted writers use the durable worker head, never their own checkout.
    return wrap_evidence(raw_result, expected, root=root), ""
