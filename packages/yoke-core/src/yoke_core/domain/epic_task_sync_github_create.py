"""Issue-creation and dedup helpers for epic-task GitHub sync.

Owns parent-epic resolution, child-task dedup, and parent github_issue
backfill. Both create paths route through the typed
:func:`yoke_core.domain.github_rest.create_issue` surface with the
compact-mirror budget guard applied via ``select_body_for_github`` so an
over-budget epic/task body swaps to the compact mirror instead of being
rejected by the REST issue-create POST.

Yoke does NOT use the ``gh`` CLI; every GitHub interaction here goes
through the typed :mod:`yoke_core.domain.github_rest` surface.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain import backlog_github_body_budget as _budget
from yoke_core.domain import backlog_github_body_writer as _writer
from yoke_core.domain import backlog_github_label_sync_rest as _label_rest
from yoke_core.domain import github_rest
from yoke_core.domain.epic_task_sync import _placeholder
from yoke_core.domain.github_dedup import search_existing_issue
from yoke_core.domain.project_github_auth import resolve_project_github_auth


def _task_id_from_epic(epic_id: str, task_num: int) -> int:
    """Pack epic_id and task_num into a stable numeric id for the budget
    guard's mirror evidence summary. The mirror keys on this id only
    when an oversized task body forces the compact path; under-budget
    bodies are sent verbatim and the id never appears on GitHub.
    """
    try:
        return int(epic_id) * 1000 + int(task_num)
    except (TypeError, ValueError):
        return int(task_num)


def _extract_issue_num(value: object) -> str:
    """Coerce an Issue/number-like result into the issue-number string.

    Retained for shape-compat with epic_task_sync_github callers that
    previously parsed the gh create-output URL; with the typed REST
    surface the returned Issue carries the number directly.
    """
    if value is None:
        return "0"
    number = getattr(value, "number", None)
    if isinstance(number, int) and number > 0:
        return str(number)
    text = str(value).strip()
    if text.isdigit():
        return text
    return "0"


def _backfill_parent_gh_issue(
    parent_item_id: str,
    issue_num: str,
    *,
    conn: Any,
) -> None:
    if parent_item_id and issue_num:
        p = _placeholder(conn)
        conn.execute(
            f"UPDATE items SET github_issue = {p} WHERE id = {p}",
            (f"#{issue_num}", int(parent_item_id)),
        )
        conn.commit()


def _create_issue_with_body_budget(
    *,
    project: str,
    title: str,
    body: str,
    labels: list[str],
    item_id: int,
    item_fields: dict,
    conn: Optional[Any],
    stderr: TextIO,
) -> Optional[github_rest.Issue]:
    """Create a GitHub issue through the typed REST surface, applying
    the compact-mirror body-budget guard so an oversized body swaps to
    the compact mirror instead of being rejected by the REST endpoint.
    Returns the created :class:`Issue`, or ``None`` on transport failure.
    """
    selected_body, mode = _budget.select_body_for_github(
        body, item_fields=item_fields, conn=conn, item_id=item_id,
    )
    try:
        issue = github_rest.create_issue(
            project=project, title=title, body=selected_body, labels=labels,
        )
    except github_rest.RestTransportError as exc:
        print(f"Error: REST create_issue failed: {exc}", file=stderr)
        return None
    _budget.emit_compact_notice(mode, item_id, stderr)
    return issue


def _resolve_or_create_epic_issue(
    *,
    epic_name: str,
    backlog_id: str,
    backlog_github_issue: str,
    parent_item_id: str,
    gh_project: str,
    dry_run: bool,
    conn: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> str:
    """Resolve, reuse, or create the epic parent GitHub issue. Returns
    the issue number as a string."""
    if dry_run:
        if backlog_github_issue:
            print(f"[DRY-RUN] Using existing backlog issue: #{backlog_github_issue}", file=stdout)
            return backlog_github_issue
        print("[DRY-RUN] Skipping GitHub: would create epic issue (using placeholder #0)", file=stdout)
        return "0"

    if backlog_github_issue:
        # Reuse the backlog item's existing GitHub issue — ensure it
        # carries the ``type:epic`` label.
        try:
            auth = resolve_project_github_auth(
                gh_project,
                required_permissions=GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
            )
            _label_rest.add_labels(
                auth.repo, int(backlog_github_issue), ["type:epic"],
                token=auth.token,
            )
        except github_rest.RestTransportError as exc:
            print(
                f"Warning: failed to add type:epic to #{backlog_github_issue}: {exc}",
                file=stderr,
            )
        print(f"Reusing backlog issue as epic parent: #{backlog_github_issue}", file=stdout)
        return backlog_github_issue

    # Read title from DB
    epic_title = ""
    if parent_item_id:
        row = conn.execute(
            f"SELECT COALESCE(title, '') FROM items WHERE id = {_placeholder(conn)}",
            (int(parent_item_id),),
        ).fetchone()
        epic_title = str(row[0] or "") if row else ""
    if not epic_title:
        epic_title = f"Epic: {epic_name}"
    if backlog_id:
        epic_title = f"[{backlog_id}] {epic_title}"

    # Dedup search — exact bracketed-prefix match required
    if backlog_id:
        found = search_existing_issue(
            f"[{backlog_id}]",
            project=gh_project,
            stderr=stderr,
        )
        if found:
            found_num, _ = found
            print(f"Found existing GitHub issue #{found_num} for {backlog_id} — reusing", file=stdout)
            _backfill_parent_gh_issue(parent_item_id, found_num, conn=conn)
            return found_num

    # Create new epic issue
    body_text = ""
    if parent_item_id:
        from yoke_core.domain.render_body import build_body
        body_text = build_body(conn, parent_item_id) or ""
    if not body_text:
        body_text = f"# Epic: {epic_name}"

    print(f"Creating epic issue: {epic_title}", file=stdout)
    issue = _create_issue_with_body_budget(
        project=gh_project,
        title=epic_title,
        body=body_text,
        labels=["type:epic"],
        item_id=int(parent_item_id) if parent_item_id else 0,
        item_fields={
            "title": epic_title,
            "status": "planning",
            "type": "epic",
            "project": gh_project,
        },
        conn=conn,
        stderr=stderr,
    )
    if issue is None:
        print("Error: Failed to create epic issue", file=sys.stderr)
        return "0"

    issue_num = _extract_issue_num(issue)
    print(f"Created epic issue: #{issue_num}", file=stdout)
    _backfill_parent_gh_issue(parent_item_id, issue_num, conn=conn)
    return issue_num


def _dedup_or_create_task_issue(
    *,
    backlog_id: str,
    task_num_str: str,
    task_title: str,
    issue_title: str,
    task_body: str,
    labels: list[str],
    gh_project: str,
    stdout: TextIO,
    stderr: TextIO,
    conn: Optional[Any] = None,
    epic_id: str = "",
    task_num: int = 0,
) -> str:
    """Search for existing task issue or create a new one. Returns issue number."""
    if backlog_id:
        # Two-pass dedup: new format, then old format. Exact bracketed-prefix
        # match required at each pass.
        found = search_existing_issue(
            f"[{backlog_id}] {task_num_str} {task_title}",
            project=gh_project,
            stderr=stderr,
        )
        if not found:
            found = search_existing_issue(
                f"[{backlog_id}] {task_title}",
                project=gh_project,
                stderr=stderr,
            )
        if found:
            found_num, _ = found
            print(f"Found existing GitHub issue #{found_num} for {issue_title} — reusing", file=stdout)
            return found_num

    # Create new issue
    print(f"Creating task issue: {issue_title}", file=stdout)
    issue = _create_issue_with_body_budget(
        project=gh_project,
        title=issue_title,
        body=task_body,
        labels=labels,
        item_id=_task_id_from_epic(epic_id, task_num),
        item_fields={
            "title": issue_title,
            "status": "planned",
            "type": "task",
            "project": gh_project,
            "identity": _writer.epic_task_identity(epic_id, task_num),
            "body_command": _writer.epic_task_body_command(epic_id, task_num),
            "next_actions": _writer.epic_task_next_actions(epic_id),
        },
        conn=conn,
        stderr=stderr,
    )
    if issue is None:
        print("Warning: Failed to create task issue", file=sys.stderr)
        return "0"

    issue_num = _extract_issue_num(issue)
    print(f"Created task issue: #{issue_num}", file=stdout)
    return issue_num
