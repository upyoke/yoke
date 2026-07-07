"""Runner-fleet Pulumi render values sourced from project capabilities."""

from __future__ import annotations

from typing import Dict

from . import json_helper
from .github_actions_runner_fleet_capability import (
    CAPABILITY_TYPE as RUNNER_FLEET_CAPABILITY_TYPE,
    RunnerFleetSettings,
    validate as validate_runner_fleet_settings,
)
from .project_renderer_settings import ProjectRendererSettings, _stringify


def runner_fleet_values(
    settings: ProjectRendererSettings, *, fallback_repo: str,
) -> Dict[str, str]:
    """Return Pulumi template values for the runner-fleet stack."""
    runner_fleet = _runner_fleet_settings(settings)
    return {
        "runner_fleet_repo": _stringify(runner_fleet.repo, fallback_repo),
        "runner_fleet_labels_json": json_helper.dumps_compact(
            runner_fleet.runner_labels
        ),
        "runner_fleet_instance_type": runner_fleet.instance.instance_type,
        "runner_fleet_architecture": runner_fleet.instance.architecture,
        "runner_fleet_root_volume_gb": str(
            runner_fleet.instance.root_volume_gb
        ),
        "runner_fleet_runner_count": str(
            runner_fleet.desired_runner_count
        ),
        "runner_fleet_max_runner_count": str(
            runner_fleet.max_runner_count
        ),
        "runner_fleet_idle_shutdown_minutes": str(
            runner_fleet.lifecycle.idle_shutdown_minutes
        ),
        "runner_fleet_shutdown_mode": runner_fleet.lifecycle.shutdown_mode,
    }


def _runner_fleet_settings(
    settings: ProjectRendererSettings,
) -> RunnerFleetSettings:
    raw = settings.capabilities.get(RUNNER_FLEET_CAPABILITY_TYPE)
    if raw:
        return validate_runner_fleet_settings(raw)
    return RunnerFleetSettings()
