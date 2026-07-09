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


def clone_outcome_action(plan: ClonePlan) -> str | None:
    if plan.outcome == CLONE_OUTCOME_MAKE_IT_MINE and plan.publish is not None:
        return "project-rehome-push"
    if plan.outcome == CLONE_OUTCOME_FORK and plan.fallback_token:
        return "project-fork-remotes"
    return None


def store_github_binding(
    progress: onboard_apply_progress.ProgressCallback | None,
    target: str,
    project: Mapping[str, Any],
    token_value: str | None,
    github_adoption: Mapping[str, Any] | None,
    config_path: str | Path | None,
) -> Mapping[str, Any] | None:
    return None


def finish_github_binding(
    progress: onboard_apply_progress.ProgressCallback | None,
    target: str,
    github_adoption: Mapping[str, Any] | None,
) -> None:
    status = "skipped" if target in ("", "skip", "backlog-only") else "done"
    onboard_apply_progress.emit(progress, "project-github-auth-choice", target, status)


__all__ = ["clone_outcome_action", "finish_github_binding", "store_github_binding"]
