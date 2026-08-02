"""Setup and finalization helpers for epic-task GitHub synchronization."""

from __future__ import annotations

from typing import Any, TextIO

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)

from yoke_core.domain.epic_task_sync_github_orchestrator_body import (
    scope_finalization_error,
)
from yoke_core.domain.epic_task_sync_local import _generate_dispatch_chains
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
)
from yoke_core.domain.projects_github_sync_mode import (
    github_sync_disabled_notice,
    github_sync_enabled,
)


def preflight_sync(
    conn: Any,
    *,
    epic_name: str,
    project: str,
    dry_run: bool,
    stdout: TextIO,
    stderr: TextIO,
    resolver,
) -> int | None:
    """Return an exit code when sync cannot proceed, otherwise ``None``."""
    if scope_finalization_error(conn, int(epic_name), stderr):
        return 1
    if not github_sync_enabled(project, conn=conn):
        print(github_sync_disabled_notice(project, "epic-task-sync"), file=stdout)
        return 0
    if dry_run:
        return None
    try:
        resolver(
            project,
            required_permissions=GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as exc:
        print(f"Error: {exc.code}: {exc}", file=stderr)
        print(f"  Repair: {repair_command_hint(exc, project)}", file=stderr)
        return 1
    return None


def load_task_rows(conn: Any, *, placeholder: str, epic_name: str):
    """Load the durable task state needed to create or link issues."""
    return conn.execute(
        f"""
        SELECT t.id, t.epic_id, t.task_num, COALESCE(t.title, ''),
               COALESCE(iw.branch, ''), COALESCE(t.context_estimate, ''),
               COALESCE(t.dependencies, ''), COALESCE(t.status, ''),
               COALESCE(t.dispatch_attempts, 0)
        FROM epic_tasks t LEFT JOIN item_worktrees iw ON iw.id=t.item_worktree_id
        WHERE t.epic_id = {placeholder}
        ORDER BY t.task_num ASC
        """,
        (epic_name,),
    ).fetchall()


def finalize_sync(
    *,
    dry_run: bool,
    has_sub_issue: bool,
    task_list_lines: list[str],
    epic_issue_num: str,
    project: str,
    parent_item_id: int | None,
    conn: Any,
    stderr: TextIO,
    repo_root: str,
    epic_name: str,
    worktree_map: list[tuple[str, str]],
    stdout: TextIO,
    created: int,
    skipped: int,
    failed_tasks: list[str],
    body_writer,
) -> int:
    """Write fallback links, local dispatch chains, and the terminal summary."""
    if not dry_run and not has_sub_issue and task_list_lines:
        body_writer(
            epic_issue_num=epic_issue_num,
            gh_project=project,
            task_list_lines=task_list_lines,
            parent_item_id=parent_item_id,
            conn=conn,
            stderr=stderr,
        )
    if repo_root:
        _generate_dispatch_chains(
            epic_name=epic_name,
            worktree_map=worktree_map,
            repo_root=repo_root,
            conn=conn,
            stdout=stdout,
        )
    print("", file=stdout)
    summary = (
        f"Sync complete: epic #{epic_issue_num} — {created} created, {skipped} skipped"
    )
    if failed_tasks:
        summary += f", {len(failed_tasks)} failed (tasks {', '.join(failed_tasks)})"
    print(summary, file=stdout)
    return 1 if failed_tasks else 0
