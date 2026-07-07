"""Local (non-GitHub) epic task sync operations.

Contains operations that write only to the local DB without making any
GitHub API calls. Currently: dispatch-chain generation.
"""

from __future__ import annotations

import datetime
import json
from typing import Any, TextIO

from yoke_core.domain import db_backend
from yoke_core.domain import project_settings
from yoke_core.domain.epic_task_sync import _placeholder


def _generate_dispatch_chains(
    *,
    epic_name: str,
    worktree_map: list[tuple[str, str]],
    repo_root: str,
    conn: Any,
    stdout: TextIO,
) -> None:
    """Generate dispatch chains in the DB for each unique worktree branch."""
    if not worktree_map:
        return

    max_attempts = project_settings.get_project_int(repo_root, "max_attempts")
    worktrees_dir = project_settings.get_project_str(repo_root, "worktrees_dir")

    # Get unique worktree branches in order
    seen: set[str] = set()
    unique_branches: list[str] = []
    for wt_branch, _ in worktree_map:
        if wt_branch not in seen:
            seen.add(wt_branch)
            unique_branches.append(wt_branch)

    for wt_branch in unique_branches:
        p = _placeholder(conn)
        # Check if chain already exists
        existing = conn.execute(
            f"SELECT id FROM epic_dispatch_chains WHERE epic_id = {p} AND worktree = {p}",
            (epic_name, wt_branch),
        ).fetchone()
        if existing:
            print(f"Dispatch chain already exists: {epic_name}/{wt_branch}", file=stdout)
            continue

        # Collect task IDs for this worktree
        task_nums = [tn for wb, tn in worktree_map if wb == wt_branch]
        wt_slug = wt_branch.replace("/", "-")
        chain_path = f"{repo_root}/{worktrees_dir}/{wt_slug}"

        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        queue_json = json.dumps(task_nums)
        first_task = task_nums[0] if task_nums else ""

        try:
            conn.execute(
                f"""INSERT INTO epic_dispatch_chains
                   (epic_id, worktree, worktree_path, queue,
                    current_index, current_task, current_attempt,
                    max_attempts, no_chain, started_at, last_updated)
                   VALUES ({p}, {p}, {p}, {p}, 0, {p}, 0, {p}, 0, '', {p})""",
                (epic_name, wt_branch, chain_path, queue_json,
                 first_task, max_attempts, timestamp),
            )
            conn.commit()
        except db_backend.operational_error_types(conn):
            conn.rollback()
            pass  # table may not exist in test fixtures

        task_count = len(task_nums)
        print(f"Generated dispatch chain: {epic_name}/{wt_branch} ({task_count} tasks)", file=stdout)
