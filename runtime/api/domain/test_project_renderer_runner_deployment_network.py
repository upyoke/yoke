"""Runner deployment-network authority and stack-resolution regressions."""

from __future__ import annotations

import pytest

from yoke_core.domain.github_actions_runner_fleet_capability import (
    RunnerFleetSettings,
)
from yoke_core.domain.project_renderer_runner_deployment_network import (
    ENVIRONMENT_ELASTIC_IP_OUTPUT,
    STANDALONE_VPS_ELASTIC_IP_OUTPUT,
    deployment_ssh_stack_names,
    deployment_ssh_stack_outputs,
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
    assert deployment_ssh_stack_outputs(settings, runner) == {
        "buzz-live": ENVIRONMENT_ELASTIC_IP_OUTPUT,
    }


def test_standalone_deployment_ssh_stacks_do_not_require_environment_rows():
    settings = _settings_from_context("yoke", {"projectName": "yoke"})
    runner = RunnerFleetSettings.model_validate({
        "network": {
            "deployment_ssh_stack_names": [
                "yoke-platform-vps", "upyoke/platform/production",
            ],
        },
    })

    assert deployment_ssh_stack_names(settings, runner) == [
        "yoke-platform-vps", "upyoke/platform/production",
    ]
    assert deployment_ssh_stack_outputs(settings, runner) == {
        "yoke-platform-vps": STANDALONE_VPS_ELASTIC_IP_OUTPUT,
        "upyoke/platform/production": STANDALONE_VPS_ELASTIC_IP_OUTPUT,
    }


def test_deployment_ssh_stacks_merge_and_dedupe_after_environments():
    settings = _settings_from_context("yoke", {"projectName": "yoke"})
    assert settings.primary_environment is not None
    settings.primary_environment.settings.clear()
    settings.primary_environment.settings.update({
        "capabilities": ["vps"],
        "pulumi": {"stack_name": "yoke-prod"},
    })
    runner = RunnerFleetSettings.model_validate({
        "network": {
            "deployment_ssh_environments": ["production"],
            "deployment_ssh_stack_names": [
                "yoke-prod", "yoke-platform-vps", "yoke-platform-vps",
            ],
        },
    })

    assert deployment_ssh_stack_names(settings, runner) == [
        "yoke-prod", "yoke-platform-vps",
    ]
    assert deployment_ssh_stack_outputs(settings, runner) == {
        "yoke-prod": ENVIRONMENT_ELASTIC_IP_OUTPUT,
        "yoke-platform-vps": STANDALONE_VPS_ELASTIC_IP_OUTPUT,
    }


@pytest.mark.parametrize(
    "stack_name",
    [
        " ",
        "org/project/stack/extra",
        "org/project stack",
        "stack:prod",
        "198.51.100.42",
        "198.51.100.42/32",
    ],
)
def test_deployment_ssh_stack_names_reject_invalid_or_literal_targets(
    stack_name,
):
    with pytest.raises(ValueError, match="Pulumi stack names"):
        RunnerFleetSettings.model_validate({
            "network": {"deployment_ssh_stack_names": [stack_name]},
        })
