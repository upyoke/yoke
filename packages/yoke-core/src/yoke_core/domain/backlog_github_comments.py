"""Backlog GitHub comments — `post_comment` posts a status-change comment
to the linked GitHub issue.

The comment owns no labels: the status label belongs to ``sync_labels``
(and ``close_issue`` on close), which the same transition already runs.

Auth-failure contract: when the canonical resolver raises
:class:`ProjectGithubAuthError`, :func:`post_comment` returns non-zero
and prints a typed-stderr diagnostic carrying the exception class name
and a concrete repair hint. The auth failure is never silently
swallowed; the structured-write caller surfaces it via a
``sync_warning`` entry on its own result dict.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain.backlog_github_sync_accessor import bgs as _bgs
from yoke_core.domain import github_rest
from yoke_core.domain.backlog_github_fetch import (
    _close_if_owned,
    _item_context,
    _item_ref,
    _open_conn,
    _resolve_item_id,
)
from yoke_core.domain.project_attribution import resolved_project


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
            print(f"Error: no item for {item_id!r}", file=stderr)
            return 1
        public_ref = _item_ref(item_pk, conn=conn)
        if _bgs()._dry_run():
            print(
                f"[DRY-RUN] Skipping GitHub: post-comment for {public_ref} ({old_status} -> {new_status})",
                file=stdout,
            )
            return 0

        context = _item_context(item_pk, conn=conn)
        if context is None:
            print(f"Error: Item {public_ref} not found", file=stderr)
            return 1
        github_issue, project, _ = context
        issue_num_str = github_issue.lstrip("#")
        if not issue_num_str or issue_num_str == "null":
            return 0
        issue_num = int(issue_num_str)

        gh_project = resolved_project(project)
        if _bgs()._github_sync_skip(gh_project, "post-comment", conn=conn, out=stdout):
            return 0
        auth = _bgs()._issue_write_auth(
            gh_project, public_ref, "post_comment", stderr=stderr
        )
        if auth is None:
            return 1

        if _bgs()._fetch_validated_issue(
            public_ref,
            str(issue_num),
            auth=auth,
            stderr=stderr,
            timeout_seconds=github_timeout_seconds,
            max_attempts=github_max_attempts,
        ) is None:
            print(
                f"Warning: post_comment skipped for {public_ref} — "
                "issue validation failed",
                file=stderr,
            )
            return 1

        github_rest.post_comment(
            project=gh_project, number=issue_num,
            body=f"**Status:** `{old_status}` → `{new_status}`",
            timeout_seconds=github_timeout_seconds,
            max_attempts=github_max_attempts,
            auth=auth,
        )
        print(f"Posted status update to {github_issue}", file=stdout)
        return 0
    finally:
        _close_if_owned(conn, owns_conn)


__all__ = ["post_comment"]
