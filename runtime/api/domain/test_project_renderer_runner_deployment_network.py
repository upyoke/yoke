"""Runner deployment-network authority and stack-resolution regressions."""

from __future__ import annotations

import pytest

from yoke_core.domain.github_actions_runner_fleet_capability import (
    RunnerFleetSettings,
)
from yoke_core.domain.project_renderer_runner_deployment_network import (
    deployment_ssh_stack_names,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)
from runtime.api.domain.test_project_renderer_pulumi import (
    _settings_from_context,
)


@pytest.mark.parametrize(
    ("selector", "environment_settings", "message"),
    [
        ("missing", {}, "match exactly one environment"),
        (
            "production",
            {"pulumi": {"activation_state": "active", "stack_name": "buzz"}},
            "declare the vps capability",
        ),
        (
            "production",
            {
                "capabilities": ["vps"],
                "pulumi": {
                    "activation_state": "render_only",
                    "stack_name": "buzz",
                },
            },
            "active Pulumi stack",
        ),
        (
            "production",
            {
                "capabilities": ["vps"],
                "pulumi": {"render_only": True, "stack_name": "buzz"},
            },
            "active Pulumi stack",
        ),
        (
            "production",
            {
                "capabilities": ["vps"],
                "pulumi": {"activation_state": "active"},
            },
            "pulumi.stack_name",
        ),
    ],
)
def test_deployment_ssh_environment_requires_active_vps_stack(
    selector, environment_settings, message,
):
    settings = _settings_from_context("buzz", {"projectName": "buzz"})
    assert settings.primary_environment is not None
    settings.primary_environment.settings.clear()
    settings.primary_environment.settings.update(environment_settings)
    runner = RunnerFleetSettings.model_validate({
        "network": {"deployment_ssh_environments": [selector]},
    })

    with pytest.raises(ValueError, match=message):
        deployment_ssh_stack_names(settings, runner)


def test_deployment_ssh_environments_require_distinct_stacks():
    shared = {
        "capabilities": ["vps"],
        "pulumi": {"activation_state": "active", "stack_name": "buzz-live"},
    }
    environments = (
        RendererEnvironmentSettings("buzz-prod", "prod", dict(shared)),
        RendererEnvironmentSettings("buzz-stage", "stage", dict(shared)),
    )
    base = _settings_from_context("buzz", {"projectName": "buzz"})
    settings = ProjectRendererSettings(
        project=base.project,
        deploy_namespace=base.deploy_namespace,
        display_name=base.display_name,
        site_id=base.site_id,
        site_settings=base.site_settings,
        primary_environment=environments[0],
        environments=environments,
        capabilities=base.capabilities,
    )
    runner = RunnerFleetSettings.model_validate({
        "network": {"deployment_ssh_environments": ["prod", "stage"]},
    })

    with pytest.raises(ValueError, match="distinct Pulumi stacks"):
        deployment_ssh_stack_names(settings, runner)


def test_deployment_ssh_environment_defaults_to_active_stack():
    settings = _settings_from_context("buzz", {"projectName": "buzz"})
    assert settings.primary_environment is not None
    settings.primary_environment.settings.clear()
    settings.primary_environment.settings.update({
        "capabilities": ["vps"],
        "pulumi": {"stack_name": "buzz-live"},
    })
    runner = RunnerFleetSettings.model_validate({
        "network": {"deployment_ssh_environments": ["production"]},
    })

    assert deployment_ssh_stack_names(settings, runner) == ["buzz-live"]
