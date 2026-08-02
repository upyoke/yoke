"""Authenticated GitHub label reads and reconciliation primitives."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS as ISSUES_READ,
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS as ISSUES_WRITE,
)
from yoke_core.domain import backlog_github_label_sync_rest as rest
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


def get_issue_labels(issue_num: str, project: str) -> list[str]:
    """Fetch labels from the verified project repository."""
    try:
        auth = resolve_project_github_auth(project, required_permissions=ISSUES_READ)
    except ProjectGithubAuthError:
        return []
    return rest.fetch_issue_labels(auth.repo, int(issue_num), token=auth.token)


def get_issue_state(issue_num: str, project: str) -> str:
    """Fetch issue state from the verified project repository."""
    try:
        auth = resolve_project_github_auth(project, required_permissions=ISSUES_READ)
    except ProjectGithubAuthError:
        return "UNKNOWN"
    return rest.fetch_issue_state(auth.repo, int(issue_num), token=auth.token)


def repo_labels(project: str) -> dict[str, str]:
    """Fetch current repository label colors keyed by name."""
    auth = resolve_project_github_auth(project, required_permissions=ISSUES_READ)
    return rest.fetch_repo_labels(auth.repo, token=auth.token)


def ensure_label(
    name: str,
    color: str,
    project: str,
    *,
    description: str = "",
    timeout_seconds: Optional[float] = None,
    max_attempts: Optional[int] = None,
) -> None:
    """Create a label in the verified repository if it does not exist."""
    auth = resolve_project_github_auth(project, required_permissions=ISSUES_WRITE)
    rest.ensure_label(
        name,
        color,
        auth.repo,
        token=auth.token,
        description=description,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )


def reconcile_category(
    prefix: str,
    want: str,
    existing: list[str],
    issue_num: str,
    project: str,
    color: str,
) -> None:
    """Reconcile one label category in the verified repository."""
    auth = resolve_project_github_auth(project, required_permissions=ISSUES_WRITE)
    has_correct = False
    for label in existing:
        if not label.startswith(prefix):
            continue
        if want and label == want:
            has_correct = True
        else:
            rest.remove_label(auth.repo, int(issue_num), label, token=auth.token)
    if not has_correct and want:
        rest.ensure_label(want, color, auth.repo, token=auth.token)
        rest.add_labels(auth.repo, int(issue_num), [want], token=auth.token)
