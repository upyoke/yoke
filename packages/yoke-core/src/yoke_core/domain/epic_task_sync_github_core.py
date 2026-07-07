"""Core sync operations — sync_progress_notes and sync_epic_tasks.

``sync_progress_notes`` lives here.  ``sync_epic_tasks`` is a thin wrapper
that delegates to ``epic_task_sync_github_orchestrator.sync_epic_tasks`` —
the wrapper preserves the patch target
``yoke_core.domain.epic_task_sync_github_core.sync_epic_tasks`` used by
the test suite.

Helpers (_ensure_label, _resolve_or_create_epic_issue, etc.) remain in
epic_task_sync_github.py and are accessed via the ``_etsg.*`` module
pattern so test patches on ``epic_task_sync_github.*`` still resolve at
call time.

Yoke does NOT use the ``gh`` CLI; every GitHub interaction here goes
through the typed :mod:`yoke_core.domain.github_rest` surface.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain import github_rest
from yoke_core.domain.epic_task_sync import (
    _connect_db,
    _epic_project_repo,
    _epic_ref_name,
    _placeholder,
)
from yoke_core.domain.projects_github_sync_mode import (
    github_sync_disabled_notice,
    github_sync_enabled,
)


def sync_progress_notes(
    epic_ref: str,
    task_ref: Optional[str] = None,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    owns_conn = conn is None
    if owns_conn:
        conn = _connect_db()
    try:
        epic_name = _epic_ref_name(epic_ref, conn=conn, stderr=stderr)
        if epic_name is None:
            return 1

        task_num_filter = None
        if task_ref not in (None, ""):
            try:
                task_num_filter = int(str(task_ref), 10)
            except ValueError:
                task_num_filter = None

        p = _placeholder(conn)
        query = f"""
            SELECT
              n.task_num,
              n.note_num,
              COALESCE(n.body, ''),
              COALESCE(t.github_issue, '')
            FROM epic_progress_notes n
            LEFT JOIN epic_tasks t
              ON t.epic_id = n.epic_id AND t.task_num = n.task_num
            WHERE n.epic_id = {p} AND n.synced_to_github = 0
        """
        params: list[object] = [epic_name]
        if task_num_filter is not None:
            query += f" AND n.task_num = {p}"
            params.append(task_num_filter)
        query += " ORDER BY n.task_num ASC, n.note_num ASC"
        rows = conn.execute(query, tuple(params)).fetchall()

        if not rows:
            return 0

        project, _repo = _epic_project_repo(epic_name, conn=conn)
        gh_project = project or "yoke"
        if not github_sync_enabled(gh_project, conn=conn):
            print(
                github_sync_disabled_notice(gh_project, "progress-note-sync"),
                file=stdout,
            )
            return 0
        synced_count = 0

        for task_num, note_num, body, github_issue in rows:
            issue_num = str(github_issue or "").lstrip("#")
            if not issue_num or issue_num == "null":
                print(
                    f"Warning: No GitHub issue found for task {task_num} — skipping note {note_num}",
                    file=stderr,
                )
                continue
            if not body:
                continue

            try:
                github_rest.post_comment(
                    project=gh_project, number=int(issue_num), body=str(body),
                )
            except github_rest.RestTransportError as exc:
                print(
                    f"Warning: Failed to post note {note_num} to issue "
                    f"#{issue_num}: {exc}",
                    file=stderr,
                )
                continue

            conn.execute(
                f"""
                UPDATE epic_progress_notes
                SET synced_to_github = 1
                WHERE epic_id = {p} AND task_num = {p} AND note_num = {p}
                """,
                (epic_name, int(task_num), int(note_num)),
            )
            conn.commit()
            synced_count += 1
            print(
                f"Synced: note {note_num} (task {task_num}) -> issue #{issue_num}",
                file=stdout,
            )

        if synced_count > 0:
            task_label = f" (task {task_ref})" if task_ref not in (None, "") else ""
            print(
                f"Synced {synced_count} new progress note(s) for epic '{epic_name}'{task_label}",
                file=stdout,
            )
    finally:
        if owns_conn and conn is not None:
            conn.close()
    return 0


def sync_epic_tasks(epic_ref, epic_dir="", **kwargs):
    from yoke_core.domain.epic_task_sync_github_orchestrator import sync_epic_tasks as _impl
    return _impl(epic_ref, epic_dir, **kwargs)
