"""Backlog GitHub comments — `post_comment` posts a status-change comment
to the linked GitHub issue and reconciles the status label in one call.

Auth-failure contract: when the typed REST surface raises
:class:`ProjectGithubAuthError` (the canonical resolver's typed
diagnostic), :func:`post_comment` translates the exception into a
non-zero return + typed-stderr diagnostic carrying the exception class
name and a concrete repair hint. The auth failure is never silently
swallowed; the structured-write caller surfaces it via a
``sync_warning`` entry on its own result dict.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain.backlog_github_sync_accessor import bgs as _bgs
from yoke_core.domain import backlog_github_label_sync_rest as _label_rest
from yoke_core.domain import github_rest
from yoke_core.domain.backlog_github_fetch import (
    _close_if_owned,
    _item_context,
    _item_ref,
    _label_colors,
    _open_conn,
    _resolve_item_id,
    _status_display_label,
)
from yoke_core.domain.backlog_github_label_sync import _ensure_label
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)


def post_comment(
    item_id: str,
    old_status: str,
    new_status: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    github_timeout_seconds: Optional[float] = None,
    github_max_attempts: Optional[int] = None,
) -> int:
    """Post a status change comment to a linked GitHub issue.

    Also updates the status label (removes old, adds new).
    No-op if github_issue is null.
    """
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    owns_conn = False
    try:
        conn, owns_conn = _open_conn(conn)
    except FileNotFoundError:
        return 0

    try:
        try:
            item_pk = _resolve_item_id(item_id, conn=conn)
        except ValueError:
            print(f"Error: Item {item_id} not found", file=stderr)
            return 1
        item_ref = _item_ref(item_pk, conn=conn)
        if _bgs()._dry_run():
            print(
                f"[DRY-RUN] Skipping GitHub: post-comment for {item_ref} ({old_status} -> {new_status})",
                file=stdout,
            )
            return 0

        context = _item_context(item_pk, conn=conn)
        if context is None:
            print(f"Error: Item {item_ref} not found", file=stderr)
            return 1
        github_issue, project, repo = context
        issue_num_str = github_issue.lstrip("#")
        if not issue_num_str or issue_num_str == "null":
            return 0
        issue_num = int(issue_num_str)

        gh_project = project or "yoke"
        if _bgs()._github_sync_skip(gh_project, "post-comment", conn=conn, out=stdout):
            return 0
        if not _bgs()._github_auth_available(gh_project):
            return 0
        colors = _label_colors()

        if not _bgs()._validate_issue_in_repo(
            item_ref,
            str(issue_num),
            repo,
            project=gh_project,
            stderr=stderr,
            timeout_seconds=github_timeout_seconds,
            max_attempts=github_max_attempts,
        ):
            print(f"Warning: post_comment skipped for {item_ref} — repo mismatch", file=stderr)
            return 0

        auth = resolve_project_github_auth(gh_project)

        # Post comment
        github_rest.post_comment(
            project=gh_project, number=issue_num,
            body=f"**Status:** `{old_status}` → `{new_status}`",
            timeout_seconds=github_timeout_seconds,
            max_attempts=github_max_attempts,
        )

        # Update status labels
        new_label = f"status:{_status_display_label(new_status)}"
        old_label = f"status:{_status_display_label(old_status)}"
        _ensure_label(
            new_label,
            colors["status"],
            repo,
            gh_project,
            timeout_seconds=github_timeout_seconds,
            max_attempts=github_max_attempts,
        )
        _label_rest.add_labels(
            auth.repo,
            issue_num,
            [new_label],
            token=auth.token,
            timeout_seconds=github_timeout_seconds,
            max_attempts=github_max_attempts,
        )
        _label_rest.remove_label(
            auth.repo,
            issue_num,
            old_label,
            token=auth.token,
            timeout_seconds=github_timeout_seconds,
            max_attempts=github_max_attempts,
        )

        print(f"Posted status update to {github_issue}", file=stdout)
        return 0
    except ProjectGithubAuthError as exc:
        print(
            f"Warning: post_comment skipped for {locals().get('item_ref', str(item_id))} — "
            f"sync_warning={exc.__class__.__name__}: {exc}",
            file=stderr,
        )
        print(
            f"  Repair: {repair_command_hint(exc, exc.project)}",
            file=stderr,
        )
        return 1
    finally:
        _close_if_owned(conn, owns_conn)


__all__ = ["post_comment"]
