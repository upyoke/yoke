"""SubagentStop hook chain processing.

Historical note: an earlier iteration of this module carried a role-aware
output gate (engineer = submission receipt present; tester = qa_runs review
row present) that refused subagent termination on miss. That gate depended on
``resolve_dispatched_epic_task`` to bind the stopping subagent to its
``(epic_id, task_num)`` via ``(parent session_id, CLAUDE_PROJECT_DIR)``. The
binding never worked: subagents inherit the parent's CLAUDE_PROJECT_DIR
(always the main repo root), so the resolver returned ``None`` for every
real-world dispatch and the conservative-block path blocked indefinitely.
The user-facing failure mode (Tester emits VERDICT text but skips
``epic review-insert``) is already caught by the conduct-side closeout flow
(``engineer-tester-closeout.md`` step 9, escalating retry chain) — that
catch-net is the load-bearing layer on both Claude and Codex. The gate is
gone; this module now only handles the issue-flow auto-commit + the
``HarnessSessionStopped`` event emission.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .agent_stop_commit import auto_commit_worktree


@dataclass
class StopContext:
    """Context accumulated during dispatch chain processing."""

    item_id: str = ""
    dispatch_type: str = "issue"
    final_status: str = ""
    auto_committed: bool = False
    auto_commit_file_count: int = 0
    auto_commit_files: str = ""
    stop_reason: str = ""
    # Retained for downstream telemetry parity even though no caller populates
    # them now — keeping the fields lets event-payload consumers stay stable
    # if a future epic-side path is reintroduced.
    epic_id: str = ""
    task_num: str = ""


def process_dispatch_chains(
    db_path: str,
    script_dir: str,
    project_root: str,
    agent_dir: str,
    session_id: str,
) -> StopContext:
    """Process a SubagentStop hook invocation.

    Handles the issue-flow auto-commit when ``CLAUDE_PROJECT_DIR`` resolves
    to a ``YOK-<num>``-named worktree path. The epic-side dispatch-chain
    branch (and its dependency on a per-subagent identity resolver) was
    removed — see the module docstring.

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
