"""Repository-wide GitHub label color reconciliation."""

from __future__ import annotations

import sys
from typing import Optional, TextIO

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS as ISSUES_WRITE,
)
from yoke_core.domain import backlog_github_label_sync_rest as rest
from yoke_core.domain import project_label_policy
from yoke_core.domain.backlog_github_fetch import REPO_LABEL_DEFINITIONS
from yoke_core.domain.backlog_github_sync_accessor import bgs
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)


def update_repo_labels(
    *,
    project: str = "yoke",
    dry_run: Optional[bool] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    resolver=resolve_project_github_auth,
) -> int:
    """Sync GitHub repository label colors from the project label policy."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    dry_run = bgs()._dry_run() if dry_run is None else dry_run
    if bgs()._github_sync_skip(project, "repo-label-sync", out=stdout):
        return 0
    if not bgs()._github_auth_available(project):
        print(
            f"Error: project '{project}' has no usable GitHub App auth for label sync.",
            file=stderr,
        )
        return 1
    try:
        auth = resolver(
            project,
            required_permissions=ISSUES_WRITE,
        )
        existing = bgs()._repo_labels(project)
        for (
            label_name,
            config_key,
            default_color,
            description,
        ) in REPO_LABEL_DEFINITIONS:
            desired = project_label_policy.get_color(config_key, default_color)
            current = existing.get(label_name, "")
            if not current:
                if dry_run:
                    print(
                        f"[DRY-RUN] Would create: {label_name} (color: {desired})",
                        file=stdout,
                    )
                    continue
                try:
                    rest.ensure_label(
                        label_name,
                        desired,
                        auth.repo,
                        token=auth.token,
                        description=description,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"Error creating: {label_name} ({exc})", file=stderr)
                    continue
                print(f"Created: {label_name} (color: {desired})", file=stdout)
                continue
            if current.lower() == desired.lower():
                print(f"OK: {label_name} (already {desired})", file=stdout)
                continue
            if dry_run:
                print(
                    f"[DRY-RUN] Would update: {label_name} ({current} -> {desired})",
                    file=stdout,
                )
                continue
            try:
                rest.ensure_label(
                    label_name,
                    desired,
                    auth.repo,
                    token=auth.token,
                    description=description,
                )
            except Exception as exc:  # noqa: BLE001
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
