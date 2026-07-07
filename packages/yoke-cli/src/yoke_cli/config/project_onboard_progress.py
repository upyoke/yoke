"""Progress helpers for project onboarding apply steps."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_MAKE_IT_MINE,
    ClonePlan,
)
from yoke_cli.config.project_github_adoption import (
    should_store_project_github_token,
)
from yoke_cli.config.project_onboard_support import store_project_github_token


def clone_outcome_action(plan: ClonePlan) -> str | None:
    if plan.outcome == CLONE_OUTCOME_MAKE_IT_MINE and plan.publish is not None:
        return "project-rehome-push"
    if plan.outcome == CLONE_OUTCOME_FORK and plan.fallback_token:
        return "project-fork-remotes"
    return None


def store_github_auth(
    progress: onboard_apply_progress.ProgressCallback | None,
    target: str,
    project: Mapping[str, Any],
    token_value: str | None,
    github_adoption: Mapping[str, Any] | None,
    config_path: str | Path | None,
) -> Mapping[str, Any] | None:
    if not token_value or not should_store_project_github_token(github_adoption):
        return None
    with onboard_apply_progress.step(progress, "project-github-auth-choice", target):
        return store_project_github_token(project, token_value, config_path)


def finish_github_auth(
    progress: onboard_apply_progress.ProgressCallback | None,
    target: str,
    github_adoption: Mapping[str, Any] | None,
) -> None:
    if should_store_project_github_token(github_adoption):
        return
    status = "skipped" if target in ("", "skip") else "done"
    onboard_apply_progress.emit(progress, "project-github-auth-choice", target, status)


__all__ = ["clone_outcome_action", "finish_github_auth", "store_github_auth"]
