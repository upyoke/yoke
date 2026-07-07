"""Pulumi renderer values sourced from project capabilities."""

from __future__ import annotations

from yoke_core.domain import project_renderer_pulumi
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from runtime.api.domain.test_project_renderer_pulumi import (
    _make_project_root,
    _settings_from_context,
)


def _with_capabilities(base: ProjectRendererSettings, capabilities: dict):
    return ProjectRendererSettings(
        project=base.project,
        display_name=base.display_name,
        site_id=base.site_id,
        site_settings=base.site_settings,
        primary_environment=base.primary_environment,
        environments=base.environments,
        capabilities=capabilities,
    )


def test_github_ci_keys_from_capability(tmp_path):
    base = _settings_from_context("buzz", {"projectName": "buzz"})
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org",
        "repo_name": "buzz",
        "ci_oidc_manage_provider": False,
    }
    root = _make_project_root(tmp_path, "buzz")

    result = project_renderer_pulumi.gather_pulumi_values(
        "buzz", root, _with_capabilities(base, capabilities),
    )

    assert result["github_repo_slug"] == "acme-org/buzz"
    assert result["manage_github_oidc_provider"] == "false"


def test_runner_fleet_keys_from_capability(tmp_path):
    base = _settings_from_context("buzz", {"projectName": "buzz"})
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org",
        "repo_name": "buzz",
    }
    capabilities["github-actions-runner-fleet"] = {
        "repo": "upyoke/yoke",
        "runner_labels": [
            "self-hosted", "Linux", "ARM64", "yoke-github-actions",
        ],
        "desired_runner_count": 4,
        "max_runner_count": 4,
        "instance": {
            "instance_type": "m7g.2xlarge",
            "architecture": "arm64",
            "root_volume_gb": 100,
        },
        "lifecycle": {
            "start_mode": "autoscaled",
            "idle_shutdown_minutes": 15,
            "shutdown_mode": "terminate",
        },
    }
    root = _make_project_root(tmp_path, "buzz")

    result = project_renderer_pulumi.gather_pulumi_values(
        "buzz", root, _with_capabilities(base, capabilities),
    )

    assert result["runner_fleet_repo"] == "upyoke/yoke"
    assert result["runner_fleet_labels_json"] == (
        '["self-hosted","Linux","ARM64","yoke-github-actions"]'
    )
    assert result["runner_fleet_instance_type"] == "m7g.2xlarge"
    assert result["runner_fleet_root_volume_gb"] == "100"
    assert result["runner_fleet_idle_shutdown_minutes"] == "15"
    assert result["runner_fleet_shutdown_mode"] == "terminate"
