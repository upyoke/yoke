"""SubagentStop hook context and worktree auto-commit processing.

A ``YOK-N`` worktree is an item lane regardless of its pinned workflow. The
hook records that item identity and applies the safety-net auto-commit.
Task-scoped event callers identify a work unit with ``item_id + task_num``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .agent_stop_commit import auto_commit_worktree


@dataclass
class StopContext:
    """Context accumulated during dispatch chain processing."""

    item_id: str = ""
    task_num: str = ""
    final_status: str = ""
    auto_committed: bool = False
    auto_commit_file_count: int = 0
    auto_commit_files: str = ""
    stop_reason: str = ""


def process_dispatch_chains(
    db_path: str,
    script_dir: str,
    project_root: str,
    agent_dir: str,
    session_id: str,
) -> StopContext:
    """Process a SubagentStop hook invocation.

    Applies the safety-net auto-commit when ``CLAUDE_PROJECT_DIR`` resolves
    to a ``YOK-<num>``-named item worktree distinct from the project root.

    Returns the accumulated context for event emission.
    """
    del db_path, script_dir, session_id  # retained for signature stability
    ctx = StopContext()

    if agent_dir:
        basename = os.path.basename(agent_dir)
        if basename.startswith("YOK-") and agent_dir != project_root:
            yok_id = basename[4:]
            result = auto_commit_worktree(agent_dir, f"YOK-{yok_id}")
            ctx.item_id = yok_id
            if result.committed:
                ctx.auto_committed = True
                ctx.auto_commit_file_count = result.file_count
                ctx.auto_commit_files = result.files

    return ctx
