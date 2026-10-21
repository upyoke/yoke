"""SubagentStop hook context and worktree auto-commit processing.

A worktree whose name resolves to an item — a recorded lane branch, or a
public ref (``PREFIX-N``) of a known project — is an item lane regardless
of its pinned workflow. The hook
applies the safety-net auto-commit and records the owning ``items.id``,
resolved through the lane registry and the project's sequence, never by
reading the number in the name.
Task-scoped event callers identify a work unit with ``item_id + task_num``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

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


def _lane_item_id(db_path: str, name: str) -> Optional[int]:
    """Resolve the lane NAME to its ``items.id``; ``None`` when unresolved."""
    if not db_path:
        return None
    from yoke_core.domain import db_helpers
    from yoke_core.domain.item_worktree_resolution import item_id_for_lane_name

    try:
        with db_helpers.connect(db_path) as conn:
            return item_id_for_lane_name(conn, name)
    except Exception:  # noqa: BLE001 - fail-open hook; no item, no commit
        return None


def process_dispatch_chains(
    db_path: str,
    script_dir: str,
    project_root: str,
    agent_dir: str,
    session_id: str,
) -> StopContext:
    """Process a SubagentStop hook invocation.

    Applies the safety-net auto-commit when ``CLAUDE_PROJECT_DIR`` is an
    item lane distinct from the project root: its basename is a public ref
    resolves to an item: a recorded lane, or a public ref of a known
    project. A folder that only looks like a ref (``app-2``) or an
    unreadable control plane commits nothing.

    Returns the accumulated context for event emission.
    """
    del script_dir, session_id  # retained for signature stability
    ctx = StopContext()

    if not agent_dir or agent_dir == project_root:
        return ctx
    name = os.path.basename(agent_dir.rstrip("/"))
    item_id = _lane_item_id(db_path, name)
    if item_id is None:
        return ctx
    result = auto_commit_worktree(agent_dir, name)
    ctx.item_id = str(item_id)
    if result.committed:
        ctx.auto_committed = True
        ctx.auto_commit_file_count = result.file_count
        ctx.auto_commit_files = result.files

    return ctx
