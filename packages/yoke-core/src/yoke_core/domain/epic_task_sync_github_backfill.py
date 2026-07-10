"""Backfill helpers — title and label backfill against existing GitHub
issues for an epic's tasks.

Yoke does NOT use the ``gh`` CLI; every GitHub interaction here goes
through the typed :mod:`yoke_core.domain.github_rest` surface.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)

import yoke_core.domain.epic_task_sync as _epic_task_sync_parent
from yoke_core.domain import backlog_github_label_sync_rest as _label_rest
from yoke_core.domain import github_rest
from yoke_core.domain import project_label_policy
from yoke_core.domain.github_constraints import clamp_label_name
from yoke_core.domain.epic_task_sync import (
    _connect_db,
    _epic_parent_item_id,
    _epic_project,
    _epic_ref_name,
    _placeholder,
    _backfill_title_has_task_num,
    LABEL_COLOR_DEFAULT,
    TYPE_LABEL_COLOR_DEFAULT,
    WORKTREE_LABEL_COLOR_DEFAULT,
)
from yoke_core.domain.project_github_auth import resolve_project_github_auth
from yoke_core.domain.projects_github_sync_mode import (
    github_sync_disabled_notice,
    github_sync_enabled,
)


def _is_dry_run() -> bool:
    """Delegate to parent module so test patches on epic_task_sync._is_dry_run are respected."""
    return _epic_task_sync_parent._is_dry_run()


def backfill_task_titles(
    epic_ref: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    if _is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: backfill-task-titles for epic {epic_ref}", file=stdout)
        return 0

    owns_conn = conn is None
    if owns_conn:
        conn = _connect_db()
    try:
        epic_name = _epic_ref_name(epic_ref, conn=conn, stderr=stderr)
        if epic_name is None:
            return 1

        parent_item_id = _epic_parent_item_id(epic_name, conn=conn)
        backlog_ref = f"YOK-{parent_item_id}" if parent_item_id else ""
        project = _epic_project(epic_name, conn=conn)
        p = _placeholder(conn)
        rows = conn.execute(
            f"""
            SELECT task_num, COALESCE(title, ''), COALESCE(github_issue, '')
            FROM epic_tasks
            WHERE epic_id = {p} AND github_issue IS NOT NULL AND github_issue <> ''
            ORDER BY task_num ASC
            """,
            (epic_name,),
        ).fetchall()

        if not rows:
            print(f"No tasks with GitHub issues found for epic {epic_name}", file=stdout)
            return 0

        gh_project = project or "yoke"
        if not github_sync_enabled(gh_project, conn=conn):
            print(
                github_sync_disabled_notice(gh_project, "backfill-task-titles"),
                file=stdout,
            )
            return 0
        for task_num, title, github_issue in rows:
            issue_num_str = str(github_issue or "").lstrip("#")
            if not issue_num_str or issue_num_str == "null":
                continue
            issue_num = int(issue_num_str)

            task_num_text = f"{int(task_num):03d}"
            try:
                issue = github_rest.get_issue(project=gh_project, number=issue_num)
            except github_rest.RestTransportError as exc:
                print(
                    f"Warning: failed to fetch issue #{issue_num}: {exc}",
                    file=stderr,
                )
                continue
            if issue is None:
                print(f"Warning: issue #{issue_num} not found", file=stderr)
                continue
            if (issue.state or "").upper() == "CLOSED":
                print(f"Skipping closed issue #{issue_num} (task {task_num_text})", file=stdout)
                continue

            current_title = issue.title
            if not current_title:
                print(f"Warning: Could not read title for issue #{issue_num}", file=stderr)
                continue

            expected_title = (
                f"[{backlog_ref}] {task_num_text} {title}"
                if backlog_ref
                else f"{task_num_text} {title}"
            )
            if current_title == expected_title:
                print(f"Already correct: #{issue_num} — {current_title}", file=stdout)
                continue
            if _backfill_title_has_task_num(current_title, task_num_text):
                print(f"Already has task number: #{issue_num} — {current_title}", file=stdout)
                continue

            try:
                github_rest.update_issue(
                    project=gh_project, number=issue_num, title=expected_title,
                )
            except github_rest.RestTransportError as exc:
                print(
                    f"Warning: Failed to update title for #{issue_num}: {exc}",
                    file=stderr,
                )
                continue
            print(f"Updated: #{issue_num} — {expected_title}", file=stdout)

        print(f"Backfill complete for epic {epic_name}", file=stdout)
        return 0
    finally:
        if owns_conn and conn is not None:
            conn.close()


def backfill_task_labels(
    epic_ref: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    if _is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: backfill-task-labels for epic {epic_ref}", file=stdout)
        return 0

    owns_conn = conn is None
    if owns_conn:
        conn = _connect_db()
    try:
        epic_name = _epic_ref_name(epic_ref, conn=conn, stderr=stderr)
        if epic_name is None:
            return 1

        color_task = project_label_policy.get_color(
            "label_color_type_task", TYPE_LABEL_COLOR_DEFAULT,
        )
        color_status = project_label_policy.get_color(
            "label_color_status", LABEL_COLOR_DEFAULT,
        )
        color_worktree = project_label_policy.get_color(
            "label_color_worktree", WORKTREE_LABEL_COLOR_DEFAULT,
        )
        project = _epic_project(epic_name, conn=conn)
        p = _placeholder(conn)
        rows = conn.execute(
            f"""
            SELECT task_num, COALESCE(worktree, ''), COALESCE(github_issue, ''), COALESCE(status, '')
            FROM epic_tasks
            WHERE epic_id = {p} AND github_issue IS NOT NULL AND github_issue <> ''
            ORDER BY task_num ASC
            """,
            (epic_name,),
        ).fetchall()

        if not rows:
            print(f"No tasks with GitHub issues found for epic {epic_name}", file=stdout)
            return 0

        gh_project = project or "yoke"
        if not github_sync_enabled(gh_project, conn=conn):
            print(
                github_sync_disabled_notice(gh_project, "backfill-task-labels"),
                file=stdout,
            )
            return 0
        try:
            auth = resolve_project_github_auth(
                gh_project,
                required_permissions=GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: auth failed for backfill_task_labels: {exc}", file=stderr)
            return 1
        target_repo = auth.repo

        for task_num, worktree, github_issue, task_status in rows:
            issue_num_str = str(github_issue or "").lstrip("#")
            if not issue_num_str or issue_num_str == "null":
                continue
            issue_num = int(issue_num_str)

            task_num_text = f"{int(task_num):03d}"
            try:
                state = _label_rest.fetch_issue_state(
                    target_repo, issue_num, token=auth.token,
                )
            except github_rest.RestTransportError as exc:
                print(
                    f"Warning: failed to fetch state for #{issue_num}: {exc}",
                    file=stderr,
                )
                continue
            if state.upper() == "CLOSED":
                print(f"Skipping closed issue #{issue_num} (task {task_num_text})", file=stdout)
                continue

            try:
                existing_labels = _label_rest.fetch_issue_labels(
                    target_repo, issue_num, token=auth.token,
                )
            except github_rest.RestTransportError as exc:
                print(
                    f"Warning: failed to fetch labels for #{issue_num}: {exc}",
                    file=stderr,
                )
                existing_labels = []

            if "type:task" not in existing_labels:
                try:
                    _label_rest.ensure_label(
                        "type:task", color_task, target_repo, token=auth.token,
                    )
                    _label_rest.add_labels(
                        target_repo, issue_num, ["type:task"], token=auth.token,
                    )
                    print(
                        f"Added type:task to #{issue_num} (task {task_num_text})",
                        file=stdout,
                    )
                except github_rest.RestTransportError as exc:
                    print(
                        f"Warning: failed to add type:task to #{issue_num}: {exc}",
                        file=stderr,
                    )

            normalized_status = str(task_status or "").strip()
            if not normalized_status or normalized_status == "null":
                normalized_status = "planned"
            target_label = f"status:{normalized_status}"

            stale_labels = [
                label
                for label in existing_labels
                if label.startswith("status:") and label != target_label
            ]
            for stale_label in stale_labels:
                try:
                    _label_rest.remove_label(
                        target_repo, issue_num, stale_label, token=auth.token,
                    )
                    print(
                        f"Removed stale {stale_label} from #{issue_num} (task {task_num_text})",
                        file=stdout,
                    )
                except github_rest.RestTransportError as exc:
                    print(
                        f"Warning: failed to remove {stale_label}: {exc}",
                        file=stderr,
                    )

            if target_label not in existing_labels:
                try:
                    _label_rest.ensure_label(
                        target_label, color_status, target_repo, token=auth.token,
                    )
                    _label_rest.add_labels(
                        target_repo, issue_num, [target_label], token=auth.token,
                    )
                    print(
                        f"Added {target_label} to #{issue_num} (task {task_num_text})",
                        file=stdout,
                    )
                except github_rest.RestTransportError as exc:
                    print(
                        f"Warning: failed to add {target_label}: {exc}",
                        file=stderr,
                    )

            if worktree:
                worktree_label = clamp_label_name(
                    f"worktree:{str(worktree).replace('/', '-')}"
                )
                if worktree_label not in existing_labels:
                    try:
                        _label_rest.ensure_label(
                            worktree_label, color_worktree, target_repo,
                            token=auth.token,
                            description=f"Worktree: {worktree}",
                        )
                        _label_rest.add_labels(
                            target_repo, issue_num, [worktree_label],
                            token=auth.token,
                        )
                        print(
                            f"Added {worktree_label} to #{issue_num} (task {task_num_text})",
                            file=stdout,
                        )
                    except github_rest.RestTransportError as exc:
                        print(
                            f"Warning: failed to add {worktree_label}: {exc}",
                            file=stderr,
                        )

        print(f"Label backfill complete for epic {epic_name}", file=stdout)
        return 0
    finally:
        if owns_conn and conn is not None:
            conn.close()
