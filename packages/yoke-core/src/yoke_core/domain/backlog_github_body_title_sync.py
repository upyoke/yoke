"""Backlog GitHub body/title sync — `sync_body` updates the rendered item
body on the linked GitHub issue, and `sync_title` updates the issue title
from the local DB title field.

``sync_body`` invokes the canonical
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
**first** — before rendering or body-budget measurement —
so :class:`ProjectGithubAuthError` short-circuits the sync and surfaces
the typed class name on stderr. The body-budget check is never invoked
on the auth-failure path.

GitHub access goes through the typed :mod:`yoke_core.domain.github_rest`
surface (bearer-token REST). Yoke does NOT use the ``gh`` CLI.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain.backlog_github_sync_accessor import bgs as _bgs
from yoke_core.domain import backlog_github_body_budget as _budget
from yoke_core.domain import github_rest
from yoke_core.domain.backlog_github_fetch import (
    _close_if_owned,
    _item_context,
    _item_fields,
    _item_ref,
    _open_conn,
    _resolve_item_id,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


def sync_body(
    item_id: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    github_timeout_seconds: Optional[float] = None,
    github_max_attempts: Optional[int] = None,
) -> int:
    """Update a GitHub issue's body from the local backlog item.

    Ordering: the canonical resolver is called BEFORE any body-size
    measurement or REST request. On :class:`ProjectGithubAuthError` the
    function returns immediately;
    :func:`backlog_github_body_budget.body_exceeds_budget` is never
    invoked on the failure path.
    """
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    owns_conn = False
    try:
        conn, owns_conn = _open_conn(conn)
    except FileNotFoundError:
        return 1

    try:
        try:
            item_pk = _resolve_item_id(item_id, conn=conn)
        except ValueError:
            print(f"Error: Item {item_id} not found", file=stderr)
            return 1
        item_ref = _item_ref(item_pk, conn=conn)
        if _bgs()._dry_run():
            print(f"[DRY-RUN] Skipping GitHub: sync-body for {item_ref}", file=stdout)
            return 0

        context = _item_context(item_pk, conn=conn)
        if context is None:
            print(f"Error: Item {item_ref} not found", file=stderr)
            return 1
        github_issue, project, repo = context
        issue_num = github_issue.lstrip("#")
        if not issue_num or issue_num == "null":
            return 0

        gh_project = project or "yoke"
        if _bgs()._github_sync_skip(gh_project, "sync-body", conn=conn, out=stdout):
            return 0
        if not _bgs()._github_auth_available(gh_project):
            print(
                f"Error: project '{gh_project}' has no usable GitHub App auth for sync-body",
                file=stderr,
            )
            return 1

        # Resolve project GitHub auth FIRST.  On any typed auth
        # failure, short-circuit without rendering the body or measuring
        # its size.
        try:
            resolve_project_github_auth(gh_project)
        except ProjectGithubAuthError as exc:
            print(
                f"Error: sync_body short-circuit for {item_ref}: "
                f"{type(exc).__name__}: {exc}",
                file=stderr,
            )
            return 1

        if not _bgs()._validate_issue_in_repo(
            item_ref, issue_num, project=gh_project, stderr=stderr,
            timeout_seconds=github_timeout_seconds,
            max_attempts=github_max_attempts,
        ):
            print(
                f"Error: sync_body skipped for {item_ref} — "
                "issue validation failed",
                file=stderr,
            )
            return 1

        # Render body on demand
        from yoke_core.domain.render_body import build_body
        body = build_body(conn, int(item_pk)) or ""

        # Body-budget gate: pick full body or compact mirror via the
        # in-memory selector — the typed REST surface accepts the body
        # string directly, no temp-file dance required.
        item_fields = _item_fields(
            item_pk, ["title", "status", "type", "project"], conn=conn,
        ) or {}
        item_fields.setdefault("identity", item_ref)
        selected_body, mode = _budget.select_body_for_github(
            body,
            item_fields=item_fields,
            conn=conn,
            item_id=int(item_pk),
        )

        try:
            github_rest.update_issue(
                project=gh_project, number=int(issue_num), body=selected_body,
                timeout_seconds=github_timeout_seconds,
                max_attempts=github_max_attempts,
            )
        except github_rest.RestTransportError as exc:
            print(f"Error: Failed to update body for {github_issue}: {exc}", file=stderr)
            return 1

        # Item-side sync state: stamp the compact-pending flag when the
        # mirror went compact; clear it when a full body landed.
        _budget.record_sync_mode(conn, int(item_pk), mode)
        _budget.emit_compact_notice(mode, int(item_pk), stderr)
        print(f"Synced body: {item_ref} → {github_issue}", file=stdout)
        return 0
    finally:
        _close_if_owned(conn, owns_conn)


def sync_title(
    item_id: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Update a GitHub issue's title from the local DB title."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    owns_conn = False
    try:
        conn, owns_conn = _open_conn(conn)
    except FileNotFoundError:
        return 1

    try:
        try:
            item_pk = _resolve_item_id(item_id, conn=conn)
        except ValueError:
            print(f"Error: Item {item_id} not found", file=stderr)
            return 1
        item_ref = _item_ref(item_pk, conn=conn)
        if _bgs()._dry_run():
            print(f"[DRY-RUN] Skipping GitHub: sync-title for {item_ref}", file=stdout)
            return 0

        context = _item_context(item_pk, conn=conn)
        if context is None:
            print(f"Error: Item {item_ref} not found", file=stderr)
            return 1
        github_issue, project, repo = context
        issue_num = github_issue.lstrip("#")
        if not issue_num or issue_num == "null":
            return 0

        gh_project = project or "yoke"
        if _bgs()._github_sync_skip(gh_project, "sync-title", conn=conn, out=stdout):
            return 0
        if not _bgs()._github_auth_available(gh_project):
            print(
                f"Error: project '{gh_project}' has no usable GitHub App auth for sync-title",
                file=stderr,
            )
            return 1

        if not _bgs()._validate_issue_in_repo(
            item_ref, issue_num, project=gh_project, stderr=stderr,
        ):
            print(
                f"Error: sync_title skipped for {item_ref} — "
                "issue validation failed",
                file=stderr,
            )
            return 1

        fields = _item_fields(item_pk, ["title"], conn=conn)
        title = fields.get("title", "") if fields else ""
        if not title:
            print(f"Error: No title found for {item_ref}", file=stderr)
            return 1

        try:
            github_rest.update_issue(
                project=gh_project, number=int(issue_num),
                title=f"[{item_ref}] {title}",
            )
        except github_rest.RestTransportError as exc:
            print(f"Error: Failed to update title for {github_issue}: {exc}", file=stderr)
            return 1

        print(f"Synced title: {item_ref} → {github_issue}", file=stdout)
        return 0
    finally:
        _close_if_owned(conn, owns_conn)


__all__ = ["sync_body", "sync_title"]
