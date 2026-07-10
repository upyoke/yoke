"""Canonical renderer-readiness check for runner-fleet status."""

from __future__ import annotations

from yoke_core.domain.github_actions_runner_fleet_capability import (
    RunnerFleetSettingsError,
)
from yoke_core.domain.project_renderer_pulumi_runner_fleet import (
    runner_fleet_values,
)
from yoke_core.domain.project_renderer_settings import (
    load_project_renderer_settings,
)


def runner_fleet_render_error(project: str) -> str | None:
    """Return the exact renderer refusal, or ``None`` when apply is viable."""
    try:
        settings = load_project_renderer_settings(project)
        runner_fleet_values(settings, fallback_repo="", enabled=True)
    except (RunnerFleetSettingsError, ValueError) as exc:
        return str(exc)
    return None


__all__ = ["runner_fleet_render_error"]
