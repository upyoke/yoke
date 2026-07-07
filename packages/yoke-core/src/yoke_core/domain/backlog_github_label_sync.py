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
canonical REST helper resolved through the project's PAT auth.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain.backlog_github_sync_accessor import bgs as _bgs
from yoke_core.domain import backlog_github_label_sync_rest as _rest
from yoke_core.domain.actors import actor_label_or_passthrough
from yoke_core.domain.backlog_github_fetch import (
    BLOCKED_LABEL_COLOR,
    REPO_LABEL_DEFINITIONS,
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
from yoke_core.domain import project_label_policy
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)


def _get_issue_labels(issue_num: str, repo: str, project: str) -> list[str]:
    """Fetch current label names for a GitHub issue."""
    try:
        auth = resolve_project_github_auth(project)
    except ProjectGithubAuthError:
        return []
    target_repo = repo or auth.repo
    return _rest.fetch_issue_labels(target_repo, int(issue_num), token=auth.token)


def _get_issue_state(issue_num: str, repo: str, project: str) -> str:
    """Get the state (OPEN/CLOSED) of a GitHub issue."""
    try:
        auth = resolve_project_github_auth(project)
    except ProjectGithubAuthError:
        return "UNKNOWN"
    target_repo = repo or auth.repo
    return _rest.fetch_issue_state(target_repo, int(issue_num), token=auth.token)


def _repo_labels(project: str) -> dict[str, str]:
    """Fetch current repo label colors keyed by label name."""
    auth = resolve_project_github_auth(project)
    return _rest.fetch_repo_labels(auth.repo, token=auth.token)


def _ensure_label(
    name: str, color: str, repo: str, project: str,
    *, description: str = "",
    timeout_seconds: Optional[float] = None,
    max_attempts: Optional[int] = None,
) -> None:
    """Create a label if it doesn't exist (idempotent)."""
    auth = resolve_project_github_auth(project)
    target_repo = repo or auth.repo
    _rest.ensure_label(
        name,
        color,
        target_repo,
        token=auth.token,
        description=description,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )


def _reconcile_category(
    prefix: str, want: str, existing: list[str], issue_num: str,
    repo: str, project: str, color: str,
) -> None:
    """Remove stale labels for a category and add the correct one."""
    auth = resolve_project_github_auth(project)
    target_repo = repo or auth.repo
    has_correct = False
    for label in existing:
        if not label.startswith(prefix):
            continue
        if want and label == want:
            has_correct = True
        else:
            _rest.remove_label(target_repo, int(issue_num), label, token=auth.token)
    if not has_correct and want:
        _rest.ensure_label(want, color, target_repo, token=auth.token)
        _rest.add_labels(target_repo, int(issue_num), [want], token=auth.token)


def update_repo_labels(
    *, project: str = "yoke",
    dry_run: Optional[bool] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Sync GitHub repo label colors from the project-local label policy."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    dry_run = _bgs()._dry_run() if dry_run is None else dry_run
    if _bgs()._github_sync_skip(project, "repo-label-sync", out=stdout):
        return 0
    if not _bgs()._pat_available(project):
        print(
            f"Error: project '{project}' has no usable GitHub PAT for label sync.",
            file=stderr,
        )
        return 1
    try:
        auth = resolve_project_github_auth(project)
        existing = _bgs()._repo_labels(project)
        for label_name, config_key, default_color, description in REPO_LABEL_DEFINITIONS:
            desired = project_label_policy.get_color(config_key, default_color)
            current = existing.get(label_name, "")
            if not current:
                if dry_run:
                    print(f"[DRY-RUN] Would create: {label_name} (color: {desired})", file=stdout)
                    continue
                try:
                    _rest.ensure_label(
                        label_name, desired, auth.repo,
                        token=auth.token, description=description,
                    )
                except Exception as exc:  # noqa: BLE001 — surface concrete reason
                    print(f"Error creating: {label_name} ({exc})", file=stderr)
                    continue
                print(f"Created: {label_name} (color: {desired})", file=stdout)
                continue
            if current.lower() == desired.lower():
                print(f"OK: {label_name} (already {desired})", file=stdout)
                continue
            if dry_run:
                print(f"[DRY-RUN] Would update: {label_name} ({current} -> {desired})", file=stdout)
                continue
            try:
                _rest.ensure_label(
                    label_name, desired, auth.repo,
                    token=auth.token, description=description,
                )
            except Exception as exc:  # noqa: BLE001 — surface concrete reason
                print(f"Error updating: {label_name} ({exc})", file=stderr)
                continue
            print(f"Updated: {label_name} ({current} -> {desired})", file=stdout)
    except ProjectGithubAuthError as exc:
        print(
            f"sync_warning={type(exc).__name__}: update_repo_labels skipped for "
            f"project={project} ({exc}). Repair: {repair_command_hint(exc, project)}",
            file=stderr,
        )
        return 1
    except RuntimeError as exc:
        print(f"Error: {exc}", file=stderr)
        return 1
    return 0


def sync_labels(
    item_id: str, *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Compare and update all GitHub labels for a backlog item.

    Idempotent. No-op if github_issue is null or PAT is unavailable.
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
        item_ref = _item_ref(item_pk, conn=conn)
        if _bgs()._dry_run():
            print(f"[DRY-RUN] Skipping GitHub: sync-labels for {item_ref}", file=stdout)
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
        if not _bgs()._pat_available(gh_project):
            return 0
        if not _bgs()._validate_issue_in_repo(
            item_ref, str(issue_num), repo, project=gh_project, stderr=stderr,
        ):
            print(f"Warning: sync_labels skipped for {item_ref} — repo mismatch",
                  file=stderr)
            return 0
        fields = _item_fields(
            item_pk,
            ["status", "priority", "type", "source", "owner", "worktree", "blocked"],
            conn=conn,
        )
        if fields is None:
            return 0

        auth = resolve_project_github_auth(gh_project)
        target_repo = repo or auth.repo
        colors = _label_colors()
        status, priority, item_type = fields["status"], fields["priority"], fields["type"]
        source_label = actor_label_or_passthrough(conn, fields["source"])
        owner_label = actor_label_or_passthrough(conn, fields["owner"])
        worktree = fields["worktree"]
        blocked = str(fields.get("blocked") or "").lower() in {"1", "true"}

        want_status = f"status:{_status_display_label(status)}" if status and status != "null" else ""
        want_priority = f"priority:{priority}" if priority and priority != "null" else ""
        want_type = f"type:{item_type}" if item_type and item_type != "null" else ""
        want_source = f"source:{source_label}" if source_label else ""
        want_owner = f"owner:{owner_label}" if owner_label else ""
        want_worktree = (
            clamp_label_name(f"worktree:{worktree.replace('/', '-')}")
            if worktree and worktree != "null" else ""
        )

        existing = _get_issue_labels(str(issue_num), repo, gh_project)
        pri_color = project_label_policy.get_color(
            f"label_color_priority_{priority}", colors["status"],
        )
        type_color = colors["type_epic"] if item_type == "epic" else colors["type_issue"]

        _reconcile_category("status:", want_status, existing, str(issue_num), target_repo, gh_project, colors["status"])
        _reconcile_category("priority:", want_priority, existing, str(issue_num), target_repo, gh_project, pri_color)
        _reconcile_category("type:", want_type, existing, str(issue_num), target_repo, gh_project, type_color)
        _reconcile_category("source:", want_source, existing, str(issue_num), target_repo, gh_project, colors["source"])
        _reconcile_category("owner:", want_owner, existing, str(issue_num), target_repo, gh_project, colors["owner"])

        if want_worktree:
            if not any(label == want_worktree for label in existing
                       if label.startswith("worktree:")):
                _rest.ensure_label(
                    want_worktree, colors["worktree"], target_repo,
                    token=auth.token, description=f"Worktree: {worktree}",
                )
                _rest.add_labels(target_repo, issue_num, [want_worktree], token=auth.token)

        has_blocked = "blocked" in existing
        if blocked and not has_blocked:
            _rest.ensure_label(
                "blocked", BLOCKED_LABEL_COLOR, target_repo,
                token=auth.token, description="Item blocked (flag)",
            )
            _rest.add_labels(target_repo, issue_num, ["blocked"], token=auth.token)
        elif not blocked and has_blocked:
            _rest.remove_label(target_repo, issue_num, "blocked", token=auth.token)

        print(
            f"Labels synced: {item_ref} → {github_issue} "
            f"(status:{status}, priority:{priority}, type:{item_type}, "
            f"source:{source_label or '-'}, owner:{owner_label or '-'})",
            file=stdout,
        )
        return 0
    finally:
        _close_if_owned(conn, owns_conn)


__all__ = [
    "_get_issue_labels", "_get_issue_state", "_repo_labels",
    "_ensure_label", "_reconcile_category", "update_repo_labels", "sync_labels",
]
