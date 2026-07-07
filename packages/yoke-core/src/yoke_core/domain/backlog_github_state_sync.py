"""Backlog GitHub issue state sync + the shared boolean-flag label engine.

Public entrypoints translate :class:`ProjectGithubAuthError` into typed
stderr diagnostics with repair hints. The public boolean-flag wrappers
(``sync_frozen_label`` / ``sync_blocked_label``) live in
``backlog_github_flag_label_sync`` and call back into
:func:`_sync_flag_label` here. GitHub access goes through the typed REST
modules; Yoke does NOT use the ``gh`` CLI.
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
    _item_fields,
    _item_ref,
    _label_colors,
    _open_conn,
    _resolve_item_id,
    _status_display_label,
)
from yoke_core.domain.backlog_github_label_sync import (
    _ensure_label,
    _get_issue_labels,
    _get_issue_state,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)


def _emit_auth_warning(
    item_ref: str, op_name: str, exc: ProjectGithubAuthError, *, stderr: TextIO,
) -> None:
    """Surface typed auth diagnostic without silent swallow."""
    print(
        f"Warning: {op_name} skipped for {item_ref} — "
        f"sync_warning={exc.__class__.__name__}: {exc}", file=stderr,
    )
    print(f"  Repair: {repair_command_hint(exc, exc.project)}", file=stderr)


def close_issue(
    item_id: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Close a GitHub issue for a done backlog item.

    Also ensures the status label is current and removes stale status labels.
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
            print(f"[DRY-RUN] Skipping GitHub: close-issue for {item_ref}", file=stdout)
            return 0

        context = _item_context(item_pk, conn=conn)
        if context is None:
            print(f"Error: Item {item_ref} not found", file=stderr)
            return 1
        github_issue, project, repo = context
        issue_num_str = github_issue.lstrip("#")
        if not issue_num_str or issue_num_str == "null":
            print(f"{item_ref} not synced to GitHub, skipping close", file=stdout)
            return 0
        issue_num = int(issue_num_str)

        gh_project = project or "yoke"
        if _bgs()._github_sync_skip(gh_project, "close-issue", conn=conn, out=stdout):
            return 0
        if not _bgs()._pat_available(gh_project):
            print(
                f"Error: project '{gh_project}' has no usable GitHub PAT",
                file=stderr,
            )
            return 1
        colors = _label_colors()

        if not _bgs()._validate_issue_in_repo(
            item_ref, str(issue_num), repo, project=gh_project, stderr=stderr,
        ):
            print(f"Warning: close_issue skipped for {item_ref} — repo mismatch", file=stderr)
            return 1

        auth = resolve_project_github_auth(gh_project)

        # Ensure status label is correct
        fields = _item_fields(item_pk, ["status"], conn=conn)
        cur_status = fields.get("status", "") if fields else ""
        if cur_status and cur_status != "null":
            want_label = f"status:{_status_display_label(cur_status)}"
            _ensure_label(want_label, colors["status"], repo, gh_project)
            existing = _get_issue_labels(str(issue_num), repo, gh_project)
            for label in existing:
                if label.startswith("status:") and label != want_label:
                    _label_rest.remove_label(auth.repo, issue_num, label, token=auth.token)
            _label_rest.add_labels(auth.repo, issue_num, [want_label], token=auth.token)

        # Check if already closed
        state = _get_issue_state(str(issue_num), repo, gh_project)
        if state == "CLOSED":
            print(f"Closed: {item_ref} -> {github_issue} (already closed)", file=stdout)
            return 0

        # Close (with status-change comment)
        try:
            github_rest.set_issue_state(
                project=gh_project, number=issue_num, state="closed",
                comment=f"Closed: status -> {cur_status or 'done'}",
            )
        except github_rest.RestTransportError as exc:
            print(f"Error: Failed to close {github_issue}: {exc}", file=stderr)
            return 1

        print(f"Closed: {item_ref} -> {github_issue}", file=stdout)
        return 0
    except ProjectGithubAuthError as exc:
        _emit_auth_warning(locals().get("item_ref", str(item_id)), "close_issue", exc, stderr=stderr)
        return 1
    finally:
        _close_if_owned(conn, owns_conn)


def reopen_issue(
    item_id: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Reopen a closed GitHub issue. Idempotent."""
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
            print(f"[DRY-RUN] Skipping GitHub: reopen-issue for {item_ref}", file=stdout)
            return 0

        context = _item_context(item_pk, conn=conn)
        if context is None:
            print(f"Error: Item {item_ref} not found", file=stderr)
            return 1
        github_issue, project, repo = context
        issue_num_str = github_issue.lstrip("#")
        if not issue_num_str or issue_num_str == "null":
            print(f"{item_ref} not synced to GitHub, skipping reopen", file=stdout)
            return 0
        issue_num = int(issue_num_str)

        gh_project = project or "yoke"
        if _bgs()._github_sync_skip(gh_project, "reopen-issue", conn=conn, out=stdout):
            return 0
        if not _bgs()._pat_available(gh_project):
            print(
                f"Error: project '{gh_project}' has no usable GitHub PAT",
                file=stderr,
            )
            return 1

        if not _bgs()._validate_issue_in_repo(
            item_ref, str(issue_num), repo, project=gh_project, stderr=stderr,
        ):
            print(f"Warning: reopen_issue skipped for {item_ref} — repo mismatch", file=stderr)
            return 1

        # Check if already open
        state = _get_issue_state(str(issue_num), repo, gh_project)
        if state == "OPEN":
            print(f"Already open: {item_ref} → {github_issue}", file=stdout)
            return 0

        try:
            github_rest.set_issue_state(
                project=gh_project, number=issue_num, state="open",
            )
        except github_rest.RestTransportError as exc:
            print(f"Error: Failed to reopen {github_issue}: {exc}", file=stderr)
            return 1

        print(f"Reopened: {item_ref} → {github_issue}", file=stdout)
        return 0
    except ProjectGithubAuthError as exc:
        _emit_auth_warning(locals().get("item_ref", str(item_id)), "reopen_issue", exc, stderr=stderr)
        return 1
    finally:
        _close_if_owned(conn, owns_conn)


def _sync_flag_label(
    item_id: str,
    value: str,
    *,
    label: str,
    color: str,
    description: str,
    log_name: str,
    conn: Optional[Any],
    stdout: TextIO,
    stderr: TextIO,
    extra_remove_on_clear: tuple = (),
) -> int:
    """Shared add/remove for boolean-flag GitHub labels.

    Used by :func:`sync_frozen_label` and :func:`sync_blocked_label` (the
    blocked addition). Both flags follow the same shape — create the
    label idempotently, then add or remove based on the boolean value —
    so the body lives once. ``extra_remove_on_clear`` lets blocked also
    scrub the obsolete ``status:blocked`` label when value is false.
    """
    owns_conn = False
    try:
        conn, owns_conn = _open_conn(conn)
    except FileNotFoundError:
        return 0

    try:
        try:
            item_pk = _resolve_item_id(item_id, conn=conn)
        except ValueError:
            return 0
        item_ref = _item_ref(item_pk, conn=conn)
        if _bgs()._dry_run():
            print(
                f"[DRY-RUN] Skipping GitHub: sync-{log_name}-label for {item_ref} ({log_name}={value})",
                file=stdout,
            )
            return 0

        context = _item_context(item_pk, conn=conn)
        if context is None:
            return 0
        github_issue, project, repo = context
        issue_num_str = github_issue.lstrip("#")
        if not issue_num_str or issue_num_str == "null":
            return 0
        issue_num = int(issue_num_str)

        gh_project = project or "yoke"
        if _bgs()._github_sync_skip(
            gh_project, f"sync-{log_name}-label", conn=conn, out=stdout,
        ):
            return 0
        if not _bgs()._pat_available(gh_project):
            return 0
        if not _bgs()._validate_issue_in_repo(
            item_ref, str(issue_num), repo, project=gh_project, stderr=stderr,
        ):
            print(
                f"Warning: sync_{log_name}_label skipped for {item_ref} — repo mismatch",
                file=stderr,
            )
            return 0

        auth = resolve_project_github_auth(gh_project)
        _label_rest.ensure_label(
            label, color, auth.repo, token=auth.token, description=description,
        )

        if str(value or "").lower() == "true":
            _label_rest.add_labels(auth.repo, issue_num, [label], token=auth.token)
            print(f"{log_name.capitalize()} label added: {item_ref} → {github_issue}", file=stdout)
        else:
            _label_rest.remove_label(auth.repo, issue_num, label, token=auth.token)
            for obsolete in extra_remove_on_clear:
                _label_rest.remove_label(auth.repo, issue_num, obsolete, token=auth.token)
            print(f"{log_name.capitalize()} label removed: {item_ref} → {github_issue}", file=stdout)
        return 0
    except ProjectGithubAuthError as exc:
        _emit_auth_warning(locals().get("item_ref", str(item_id)), f"sync_{log_name}_label", exc, stderr=stderr)
        return 1
    finally:
        _close_if_owned(conn, owns_conn)


__all__ = [
    "close_issue",
    "reopen_issue",
    "_sync_flag_label",
]
