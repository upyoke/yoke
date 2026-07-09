"""Batched GitHub closeout sync for done-transition.

The closeout body update routes through
:func:`backlog_github_body_writer.update_issue_body_typed` so the
compact-mirror budget guard catches over-budget rendered bodies before
the REST issue-edit endpoint rejects them with ``GraphQL: Body is too
long``. Label add/remove and the issue close call use the typed REST
surface directly.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain.backlog_github_sync_accessor import bgs as _bgs
from yoke_core.domain import backlog_github_body_writer as _writer
from yoke_core.domain import backlog_github_label_sync_rest as _label_rest
from yoke_core.domain import github_rest
from yoke_core.domain.actors import actor_label_or_passthrough
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
from yoke_core.domain.project_github_auth import resolve_project_github_auth
from yoke_core.domain import project_label_policy


def _issue_snapshot(issue_num: int, repo: str, project: str) -> tuple[list[str], str]:
    """Fetch labels + state for an issue via typed REST."""
    try:
        auth = resolve_project_github_auth(project)
    except Exception:  # noqa: BLE001
        return [], "UNKNOWN"
    target_repo = repo or auth.repo
    try:
        issue = github_rest.get_issue(
            project=project, number=issue_num,
        )
    except github_rest.RestTransportError:
        return [], "UNKNOWN"
    if issue is None:
        return [], "UNKNOWN"
    return list(issue.labels), issue.state or "UNKNOWN"


def sync_done_item(
    item_id: str,
    old_status: str = "",
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Sync labels, body, close state, and status comment for a done item."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    owns_conn = False
    try:
        conn, owns_conn = _open_conn(conn)
        try:
            item_pk = _resolve_item_id(item_id, conn=conn)
        except ValueError:
            print(f"Error: Item {item_id} not found", file=stderr)
            return 1
        item_ref = _item_ref(item_pk, conn=conn)
        if _bgs()._dry_run():
            print(f"[DRY-RUN] Skipping GitHub: sync-done-item for {item_ref}", file=stdout)
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
        if _bgs()._github_sync_skip(gh_project, "sync-done-item", conn=conn, out=stdout):
            return 0
        if not _bgs()._github_auth_available(gh_project):
            return 0
        if not _bgs()._validate_issue_in_repo(
            item_ref, str(issue_num), repo, project=gh_project, stderr=stderr
        ):
            print(f"Error: sync_done_item skipped for {item_ref}", file=stderr)
            return 1

        fields = _item_fields(
            item_pk,
            ["title", "status", "priority", "type", "source", "owner", "worktree", "project"],
            conn=conn,
        )
        if fields is None:
            return 0

        existing_labels, state = _issue_snapshot(issue_num, repo, gh_project)
        colors = _label_colors()
        source_label = actor_label_or_passthrough(conn, fields["source"])
        owner_label = actor_label_or_passthrough(conn, fields["owner"])
        desired = {
            "status:": f"status:{_status_display_label(fields['status'])}",
            "priority:": f"priority:{fields['priority']}",
            "type:": f"type:{fields['type']}",
            "source:": f"source:{source_label}" if source_label else "",
            "owner:": f"owner:{owner_label}" if owner_label else "",
            "worktree:": "",
        }
        label_colors = {
            desired["status:"]: colors["status"],
            desired["priority:"]: project_label_policy.get_color(
                f"label_color_priority_{fields['priority']}", colors["status"]
            ),
            desired["type:"]: (
                colors["type_epic"] if fields["type"] == "epic" else colors["type_issue"]
            ),
            desired["source:"]: colors["source"],
            desired["owner:"]: colors["owner"],
        }

        remove_labels: list[str] = []
        add_labels: list[str] = []
        for prefix, want in desired.items():
            matches = [label for label in existing_labels if label.startswith(prefix)]
            remove_labels.extend(label for label in matches if label != want)
            if want and want not in matches:
                add_labels.append(want)

        for label in add_labels:
            _bgs()._ensure_label(label, label_colors.get(label, colors["status"]), repo, gh_project)

        from yoke_core.domain.render_body import build_body

        body = build_body(conn, int(item_pk)) or ""

        body_item_fields = {
            "title": fields.get("title", ""),
            "status": fields.get("status", ""),
            "type": fields.get("type", ""),
            "project": fields.get("project") or gh_project,
            "identity": item_ref,
        }

        edit = _writer.update_issue_body_typed(
            project=gh_project,
            number=issue_num,
            body=body,
            item_fields=body_item_fields,
            conn=conn,
            item_id=int(item_pk),
            stderr=stderr,
        )
        if edit.returncode != 0:
            print(f"Error: Failed to update {github_issue}: {edit.stderr}", file=stderr)
            return 1
        # Item-mirror sync state: stamp/clear the compact-pending flag.
        from yoke_core.domain import backlog_github_body_budget as _budget

        _budget.record_sync_mode(conn, int(item_pk), edit.mode)

        try:
            auth = resolve_project_github_auth(gh_project)
        except Exception as exc:  # noqa: BLE001
            print(f"Error: auth failed mid-flow for {github_issue}: {exc}", file=stderr)
            return 1
        target_repo = repo or auth.repo
        if add_labels:
            try:
                _label_rest.add_labels(target_repo, issue_num, add_labels, token=auth.token)
            except github_rest.RestTransportError as exc:
                print(f"Error: add labels failed for {github_issue}: {exc}", file=stderr)
                return 1
        for label in remove_labels:
            try:
                _label_rest.remove_label(target_repo, issue_num, label, token=auth.token)
            except github_rest.RestTransportError as exc:
                print(f"Error: remove label {label} failed for {github_issue}: {exc}", file=stderr)
                return 1

        if state != "CLOSED":
            close_body = (
                f"**Status:** `{old_status}` -> `done`" if old_status
                else "Closed: status -> done"
            )
            try:
                github_rest.set_issue_state(
                    project=gh_project, number=issue_num, state="closed",
                    comment=close_body,
                )
            except github_rest.RestTransportError as exc:
                print(f"Error: Failed to close {github_issue}: {exc}", file=stderr)
                return 1

        if edit.is_compact:
            print(
                f"Done sync: {item_ref} -> {github_issue} (compact mirror)",
                file=stdout,
            )
        else:
            print(f"Done sync: {item_ref} -> {github_issue}", file=stdout)
        return 0
    finally:
        _close_if_owned(conn, owns_conn)


__all__ = ["sync_done_item"]
