"""Backlog GitHub label sync — repo-wide label color reconciliation
(`update_repo_labels`) and per-issue label reconciliation (`sync_labels`).

REST label primitives (``add_labels`` / ``remove_label`` /
``set_labels`` / ``fetch_issue_labels`` / ``fetch_issue_state`` /
``fetch_repo_labels`` / ``ensure_label``) live in the sibling
:mod:`backlog_github_label_sync_rest` and are called directly here. This
module focuses on local sync orchestration (DB reads, color resolution,
idempotency).

The private helpers ``_get_issue_labels`` / ``_get_issue_state`` /
``_repo_labels`` / ``_ensure_label`` / ``_reconcile_category`` remain
exported for the other sync siblings; each is a thin wrapper around the
canonical REST helper resolved through the project's GitHub App auth.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS as ISSUES_WRITE,
)
from yoke_core.domain.backlog_github_sync_accessor import bgs as _bgs
from yoke_core.domain.backlog_github_label_resolution import (
    ensure_label as _ensure_label_impl,
    get_issue_labels as _get_issue_labels_impl,
    get_issue_state as _get_issue_state_impl,
    reconcile_category as _reconcile_category_impl,
    repo_labels as _repo_labels_impl,
)
from yoke_core.domain.backlog_github_repo_label_sync import (
    update_repo_labels as _update_repo_labels,
)
from yoke_core.domain import backlog_github_label_sync_rest as _rest
from yoke_core.domain import project_label_policy
from yoke_core.domain.actors import actor_label_or_passthrough
from yoke_core.domain.backlog_github_fetch import (
    BLOCKED_LABEL_COLOR,
    _close_if_owned,
    _item_context,
    _item_fields,
    _item_ref,
    _label_colors,
    _open_conn,
    _resolve_item_id,
    _status_display_label,
)
from yoke_core.domain.github_constraints import clamp_label_name
from yoke_core.domain.project_github_auth import (
    resolve_project_github_auth,
)


def _get_issue_labels(issue_num: str, repo: str, project: str) -> list[str]:
    return _get_issue_labels_impl(
        issue_num, project, resolver=resolve_project_github_auth
    )


def _get_issue_state(issue_num: str, repo: str, project: str) -> str:
    return _get_issue_state_impl(
        issue_num, project, resolver=resolve_project_github_auth
    )


def _repo_labels(project: str) -> dict[str, str]:
    return _repo_labels_impl(project, resolver=resolve_project_github_auth)


def _ensure_label(
    name: str,
    color: str,
    repo: str,
    project: str,
    **kwargs: object,
) -> None:
    _ensure_label_impl(
        name, color, project, resolver=resolve_project_github_auth, **kwargs
    )


def _reconcile_category(
    prefix: str,
    want: str,
    existing: list[str],
    issue_num: str,
    repo: str,
    project: str,
    color: str,
) -> None:
    _reconcile_category_impl(
        prefix,
        want,
        existing,
        issue_num,
        project,
        color,
        resolver=resolve_project_github_auth,
    )


def update_repo_labels(
    *,
    project: str = "yoke",
    dry_run: Optional[bool] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Synchronize repository labels through the patchable auth boundary."""
    return _update_repo_labels(
        project=project,
        dry_run=dry_run,
        stdout=stdout,
        stderr=stderr,
        resolver=resolve_project_github_auth,
    )


def sync_labels(
    item_id: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Compare and update all GitHub labels for a backlog item.

    Idempotent. No-op if github_issue is null or GitHub sync is disabled.
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
            return 0
        public_ref = _item_ref(item_pk, conn=conn)
        if _bgs()._dry_run():
            print(f"[DRY-RUN] Skipping GitHub: sync-labels for {public_ref}", file=stdout)
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
        if _bgs()._github_sync_skip(gh_project, "sync-labels", conn=conn, out=stdout):
            return 0
        if not _bgs()._github_auth_available(gh_project):
            print(
                f"Error: project '{gh_project}' has no usable GitHub App auth "
                "for sync-labels",
                file=stderr,
            )
            return 1
        if not _bgs()._validate_issue_in_repo(
            public_ref,
            str(issue_num),
            project=gh_project,
            stderr=stderr,
        ):
            print(
                f"Warning: sync_labels skipped for {public_ref} — "
                "issue validation failed",
                file=stderr,
            )
            return 1
        fields = _item_fields(
            item_pk,
            ["status", "priority", "workflow_id", "source", "owner", "blocked"],
            conn=conn,
        )
        if fields is None:
            return 0

        auth = resolve_project_github_auth(
            gh_project,
            required_permissions=ISSUES_WRITE,
        )
        target_repo = auth.repo
        colors = _label_colors()
        status, priority = fields["status"], fields["priority"]
        workflow_id = fields["workflow_id"]
        source_label = actor_label_or_passthrough(conn, fields["source"])
        owner_label = actor_label_or_passthrough(conn, fields["owner"])
        from yoke_core.domain.item_worktrees import primary_item_worktree

        active_lane = primary_item_worktree(conn, int(item_pk))
        worktree = str(active_lane["branch"]) if active_lane else ""
        blocked = str(fields.get("blocked") or "").lower() in {"1", "true"}

        want_status = (
            f"status:{_status_display_label(status)}"
            if status and status != "null"
            else ""
        )
        want_priority = (
            f"priority:{priority}" if priority and priority != "null" else ""
        )
        want_workflow = (
            f"workflow:{workflow_id}" if workflow_id and workflow_id != "null" else ""
        )
        want_source = f"source:{source_label}" if source_label else ""
        want_owner = f"owner:{owner_label}" if owner_label else ""
        want_worktree = (
            clamp_label_name(f"worktree:{worktree.replace('/', '-')}")
            if worktree and worktree != "null"
            else ""
        )

        existing = _get_issue_labels(str(issue_num), repo, gh_project)
        pri_color = project_label_policy.get_color(
            f"label_color_priority_{priority}",
            colors["status"],
        )
        _reconcile_category(
            "status:",
            want_status,
            existing,
            str(issue_num),
            target_repo,
            gh_project,
            colors["status"],
        )
        _reconcile_category(
            "priority:",
            want_priority,
            existing,
            str(issue_num),
            target_repo,
            gh_project,
            pri_color,
        )
        _reconcile_category(
            "workflow:",
            want_workflow,
            existing,
            str(issue_num),
            target_repo,
            gh_project,
            colors["workflow"],
        )
        _reconcile_category(
            "type:",
            "",
            existing,
            str(issue_num),
            target_repo,
            gh_project,
            colors["workflow"],
        )
        _reconcile_category(
            "source:",
            want_source,
            existing,
            str(issue_num),
            target_repo,
            gh_project,
            colors["source"],
        )
        _reconcile_category(
            "owner:",
            want_owner,
            existing,
            str(issue_num),
            target_repo,
            gh_project,
            colors["owner"],
        )

        if want_worktree:
            if not any(
                label == want_worktree
                for label in existing
                if label.startswith("worktree:")
            ):
                _rest.ensure_label(
                    want_worktree,
                    colors["worktree"],
                    target_repo,
                    token=auth.token,
                    description=f"Worktree: {worktree}",
                )
                _rest.add_labels(
                    target_repo, issue_num, [want_worktree], token=auth.token
                )
        else:
            for label in existing:
                if label.startswith("worktree:"):
                    _rest.remove_label(
                        target_repo,
                        issue_num,
                        label,
                        token=auth.token,
                    )

        has_blocked = "blocked" in existing
        if blocked and not has_blocked:
            _rest.ensure_label(
                "blocked",
                BLOCKED_LABEL_COLOR,
                target_repo,
                token=auth.token,
                description="Item blocked (flag)",
            )
            _rest.add_labels(target_repo, issue_num, ["blocked"], token=auth.token)
        elif not blocked and has_blocked:
            _rest.remove_label(target_repo, issue_num, "blocked", token=auth.token)

        print(
            f"Labels synced: {public_ref} → {github_issue} "
            f"(status:{status}, priority:{priority}, workflow:{workflow_id}, "
            f"source:{source_label or '-'}, owner:{owner_label or '-'})",
            file=stdout,
        )
        return 0
    finally:
        _close_if_owned(conn, owns_conn)


__all__ = [
    "_get_issue_labels",
    "_get_issue_state",
    "_repo_labels",
    "_ensure_label",
    "_reconcile_category",
    "update_repo_labels",
    "sync_labels",
]
