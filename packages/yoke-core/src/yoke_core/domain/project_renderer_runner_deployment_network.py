"""Deployment-network authority for the disposable Actions runner fleet."""

from __future__ import annotations

from typing import Mapping

from .github_actions_runner_fleet_capability import RunnerFleetSettings
from .project_renderer_settings import ProjectRendererSettings


ENVIRONMENT_ELASTIC_IP_OUTPUT = "originElasticIpAddress"
STANDALONE_VPS_ELASTIC_IP_OUTPUT = "vpsElasticIpAddress"
STANDALONE_VPS_SECURITY_GROUP_OUTPUT = "vpsSecurityGroupId"


def deployment_ssh_stack_names(
    settings: ProjectRendererSettings,
    runner_fleet: RunnerFleetSettings,
) -> list[str]:
    """Resolve every explicitly allowed deployment SSH Pulumi stack."""
    return list(deployment_ssh_stack_outputs(settings, runner_fleet))


def deployment_ssh_stack_outputs(
    settings: ProjectRendererSettings,
    runner_fleet: RunnerFleetSettings,
) -> dict[str, str]:
    """Bind every allowed stack to its established Elastic IP output."""
    network = runner_fleet.network
    if network is None:
        return {}
    resolved: dict[str, str] = {}
    for selector in network.deployment_ssh_environments:
        matches = [
            environment
            for environment in settings.environments
            if selector in {environment.id, environment.name}
        ]
        if len(matches) != 1:
            raise ValueError(
                "runner-fleet network.deployment_ssh_environments entries "
                "must each match exactly one environment id or name; "
                f"{selector!r} matched {len(matches)}"
            )
        environment = matches[0]
        capabilities = environment.settings.get("capabilities")
        if not isinstance(capabilities, list) or "vps" not in capabilities:
            raise ValueError(
                "runner-fleet deployment SSH environments must declare the "
                "vps capability"
            )
        pulumi_settings = environment.settings.get("pulumi")
        if not isinstance(pulumi_settings, Mapping):
            raise ValueError(
                "runner-fleet deployment SSH environments must declare "
                "settings.pulumi"
            )
        activation_state = str(
            pulumi_settings.get("activation_state") or "active"
        )
        render_only = (
            bool(pulumi_settings.get("render_only"))
            or activation_state == "render_only"
        )
        if render_only or activation_state != "active":
            raise ValueError(
                "runner-fleet deployment SSH environments must have an "
                "active Pulumi stack"
            )
        stack_name = str(pulumi_settings.get("stack_name") or "").strip()
        if not stack_name:
            raise ValueError(
                "runner-fleet deployment SSH environments must declare "
                "settings.pulumi.stack_name"
            )
        if stack_name in resolved:
            raise ValueError(
                "runner-fleet deployment SSH environments must resolve to "
                "distinct Pulumi stacks"
            )
        resolved[stack_name] = ENVIRONMENT_ELASTIC_IP_OUTPUT
    for stack_name in network.deployment_ssh_stack_names:
        if stack_name not in resolved:
            resolved[stack_name] = STANDALONE_VPS_ELASTIC_IP_OUTPUT
    return resolved


__all__ = [
    "ENVIRONMENT_ELASTIC_IP_OUTPUT",
    "STANDALONE_VPS_ELASTIC_IP_OUTPUT",
    "STANDALONE_VPS_SECURITY_GROUP_OUTPUT",
    "deployment_ssh_stack_names",
    "deployment_ssh_stack_outputs",
]
