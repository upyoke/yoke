"""Python owner for epic-task status mutation orchestration.

Owns the DB status update plus the side-effect dispatch and parent-epic
derivation for epic-task lifecycle transitions.

Responsibilities live across responsibility-named siblings:

- ``update_status_helpers`` -- shared low-level helpers (board rebuild,
  history insert, claim verification, repo resolution).
- ``update_status_auto_unblock`` -- ``auto_unblock`` dependency-aware
  unblock pass.
- ``update_status_auto_derive`` -- ``auto_derive_epic_status`` parent
  recomputation.
- ``update_status_github_sync`` -- ``_github_label_sync``,
  ``_github_comment_post``, ``_github_close_on_terminal`` (bearer-token REST).
- ``update_status_epic_checkbox`` -- ``_update_epic_checkbox`` parent
  body writeback (bearer-token REST).

This front door keeps ``update_task_status`` (the public mutator that
orchestrates all of the above) and ``main`` (the CLI entry point).  The full
historical public surface is re-exported here so existing
``from yoke_core.domain.update_status import ...`` callers continue to
work unchanged.

CLI usage::

    python3 -m yoke_core.domain.update_status <epic-id> <task-num> <new-status> [note] \\
        [--no-rebuild] [--no-github] [--no-derive]
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional, TextIO

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, query_one, query_scalar
from yoke_core.domain.github_constraints import is_real_issue_num
from yoke_core.domain.lifecycle import is_valid_task_status

# Re-export shared low-level helpers so existing callers see no change.
from yoke_core.domain.update_status_helpers import (  # noqa: F401
    RETRY_DELAYS,
    RETRY_MARKERS,
    _emit_event,
    _history_insert,
    _is_dry_run,
    _now_iso,
    _rebuild_board,
    _repo_args,
    _repo_root,
    _resolve_repo_for_epic,
    _yoke_root,
    _verify_claim,
)

# Re-export side-effect helpers from canonical owner siblings (no two-hop).
from yoke_core.domain.update_status_auto_derive import (  # noqa: F401
    auto_derive_epic_status,
)
from yoke_core.domain.update_status_auto_unblock import auto_unblock  # noqa: F401
from yoke_core.domain.update_status_epic_checkbox import (  # noqa: F401
    _update_epic_checkbox,
)
from yoke_core.domain.update_status_github_sync import (  # noqa: F401
    _github_close_on_terminal,
    _github_comment_post,
    _github_label_sync,
)

__all__ = [
    "RETRY_DELAYS",
    "RETRY_MARKERS",
    "_emit_event",
    "_github_close_on_terminal",
    "_github_comment_post",
    "_github_label_sync",
    "_history_insert",
    "_is_dry_run",
    "_now_iso",
    "_rebuild_board",
    "_repo_args",
    "_repo_root",
    "_resolve_repo_for_epic",
    "_yoke_root",
    "_update_epic_checkbox",
    "_verify_claim",
    "auto_derive_epic_status",
    "auto_unblock",
    "main",
    "update_task_status",
]


# ---------------------------------------------------------------------------
# Core: DB status update
# ---------------------------------------------------------------------------


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def update_task_status(
    conn: Any,
    epic_id: str,
    task_num: str,
    new_status: str,
    note: str = "",
    *,
    no_rebuild: bool = False,
    no_github: bool = False,
    no_derive: bool = False,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Full epic-task status mutation with all side effects.

    Returns 0 on success, non-zero on failure.
    """
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    timestamp = _now_iso()
    p = _p(conn)

    # --- Validate status ---
    if not is_valid_task_status(new_status):
        print(f"Error: invalid task status '{new_status}'", file=stderr)
        return 1

    # --- Look up current task ---
    row = query_one(
        conn,
        f"""SELECT id, epic_id, task_num, title, worktree,
                  context_estimate, dependencies, status, dispatch_attempts,
                  COALESCE(github_issue, '') as github_issue
           FROM epic_tasks WHERE epic_id={p} AND task_num={p}""",
        (str(epic_id), str(task_num)),
    )
    if row is None:
        print(f"Error: Task {epic_id}/{task_num} not found in DB", file=stderr)
        return 1

    old_status = row["status"]
    github_issue = row["github_issue"]
    dispatch_attempts = row["dispatch_attempts"] or 0

    if old_status == new_status and not note:
        return 0

    # --- done guard ---
    if new_status == "done" and os.environ.get("YOKE_TASK_DONE_VERIFIED", "0") != "1":
        print("Error: epic-task done requires merge-verified context.", file=stderr)
        print("Epic tasks should reach 'reviewed-implementation' via conduct, then 'done' only through:", file=stderr)
        print("  - done-transition.sh (parent epic cascade)", file=stderr)
        print("  - merge/SKILL.md (post-PR-merge)", file=stderr)
        print("Set YOKE_TASK_DONE_VERIFIED=1 to override.", file=stderr)
        return 4

    # --- claim verification ---
    _verify_claim(epic_id, task_num, stderr=stderr)

    # --- DB update ---
    conn.execute(
        f"UPDATE epic_tasks SET status={p} WHERE epic_id={p} AND task_num={p}",
        (new_status, str(epic_id), str(task_num)),
    )
    conn.commit()

    # Update last_heartbeat
    conn.execute(
        f"UPDATE epic_tasks SET last_heartbeat={p} WHERE epic_id={p} AND task_num={p}",
        (timestamp, str(epic_id), str(task_num)),
    )
    conn.commit()

    # Increment dispatch_attempts on implementing transition
    if new_status == "implementing":
        conn.execute(
            f"UPDATE epic_tasks SET dispatch_attempts={p} WHERE epic_id={p} AND task_num={p}",
            (dispatch_attempts + 1, str(epic_id), str(task_num)),
        )
        conn.commit()

    # Record the transition (state) + history insert (TaskStatusChanged telemetry)
    from yoke_core.domain.item_status_transitions import record_task_transition
    record_task_transition(
        conn,
        epic_id=epic_id,
        task_num=task_num,
        from_status=old_status,
        to_status=new_status,
        source=os.environ.get("YOKE_STATUS_SOURCE", "update-status"),
    )
    conn.commit()
    _history_insert(epic_id, task_num, old_status, new_status, note)

    print(f"Status updated: {old_status} → {new_status} (task {task_num})", file=stdout)

    # --- Board rebuild ---
    if not no_rebuild:
        _rebuild_board()

    # --- Auto-unblock ---
    if not no_derive:
        auto_unblock(conn, epic_id, task_num, new_status, stdout=stdout, stderr=stderr)

    # --- Auto-derive parent epic status ---
    if not no_derive:
        auto_derive_epic_status(conn, epic_id, new_status, stdout=stdout, stderr=stderr)

    # --- GitHub side effects ---
    if no_github:
        return 0

    project, repo = _resolve_repo_for_epic(conn, epic_id)

    # Re-read github_issue from DB if needed
    if not github_issue:
        val = query_scalar(
            conn,
            f"SELECT COALESCE(github_issue, '') FROM epic_tasks WHERE epic_id={p} AND task_num={p}",
            (str(epic_id), str(task_num)),
        )
        github_issue = str(val) if val else ""

    # No linked issue -> nothing to sync. GitHub App auth resolution + transport errors
    # surface inside the helpers below as actionable warnings (NFR-2).
    if not github_issue:
        return 0

    issue_num = github_issue.lstrip("#")
    if not issue_num or issue_num == "null":
        return 0
    # Reject the failure-mode sentinel: a prior sync that hit a REST 422
    # would previously stamp '#0' into epic_tasks.github_issue, and the
    # status-comment path then tried to POST to /issues/0/comments — emit
    # the same advisory the no-issue branch above does instead.
    if not is_real_issue_num(github_issue):
        print(
            f"Warning: epic task {epic_id}/{task_num} has sentinel "
            f"github_issue={github_issue!r}; skipping GitHub sync until "
            f"a real issue is linked.",
            file=stderr,
        )
        return 0

    repo_a = _repo_args(repo)
    gh_project = project or "yoke"

    _github_label_sync(issue_num, new_status, repo_a, gh_project, stderr=stderr)
    _github_comment_post(issue_num, old_status, new_status, note, repo_a, gh_project, stderr=stderr)
    _github_close_on_terminal(issue_num, new_status, epic_id, task_num, repo_a, gh_project, stderr=stderr)
    _update_epic_checkbox(conn, epic_id, task_num, new_status, github_issue, repo_a, gh_project, stdout=stdout)

    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    no_rebuild = False
    no_github = False
    no_derive = False
    positionals: list[str] = []

    for arg in args:
        if arg == "--no-rebuild":
            no_rebuild = True
        elif arg == "--no-github":
            no_github = True
        elif arg == "--no-derive":
            no_derive = True
        else:
            positionals.append(arg)

    if len(positionals) < 3:
        print(
            "Usage: python3 -m yoke_core.domain.update_status <epic-id> <task-num> <new-status> [note]",
            file=sys.stderr,
        )
        return 2

    epic_ref = positionals[0]
    task_num = positionals[1]
    new_status = positionals[2]
    note = positionals[3] if len(positionals) > 3 else ""

    # Parse epic ref
    import re
    epic_id = re.sub(r"^[Yy][Oo][Kk]-", "", epic_ref).lstrip("0") or "0"

    conn = connect()
    try:
        return update_task_status(
            conn, epic_id, task_num, new_status, note,
            no_rebuild=no_rebuild,
            no_github=no_github,
            no_derive=no_derive,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
