"""Canonical runner-stack intent bound to one validated settings snapshot."""

from __future__ import annotations

import hashlib
from typing import Mapping

from yoke_core.domain import json_helper
from yoke_core.domain.project_renderer_pulumi_runner_fleet import (
    runner_fleet_stack_name,
    runner_fleet_values,
)
from yoke_core.domain.github_actions_runner_fleet_capability import (
    CAPABILITY_TYPE as RUNNER_FLEET_CAPABILITY_TYPE,
    RunnerFleetSettings,
    validate as validate_runner_fleet_settings,
)
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from yoke_core.domain.project_renderer_runner_deployment_network import (
    ENVIRONMENT_ELASTIC_IP_OUTPUT,
    STANDALONE_VPS_ELASTIC_IP_OUTPUT,
)


def authority_intent_envelope(
    settings: ProjectRendererSettings,
    values: Mapping[str, str],
    *,
    aws_capability: str,
    aws_region: str,
) -> str:
    """Serialize every snapshot-derived mutable runner-stack input."""
    labels = json_helper.loads_text(values["runner_fleet_labels_json"])
    if not isinstance(labels, list) or any(
        not isinstance(label, str) for label in labels
    ):
        raise ValueError("runner-fleet labels must be a JSON string array")
    deployment_ssh_stack_outputs = json_helper.loads_text(
        values["runner_fleet_deployment_ssh_stack_outputs_json"]
    )
    allowed_outputs = {
        ENVIRONMENT_ELASTIC_IP_OUTPUT,
        STANDALONE_VPS_ELASTIC_IP_OUTPUT,
    }
    if not isinstance(deployment_ssh_stack_outputs, dict) or any(
        not isinstance(stack_name, str)
        or not stack_name
        or not isinstance(output_name, str)
        or output_name not in allowed_outputs
        for stack_name, output_name in deployment_ssh_stack_outputs.items()
    ):
        raise ValueError(
            "runner-fleet deployment SSH stacks must map names to established "
            "Elastic IP outputs"
        )
    deployment_ssh_stack_outputs = dict(
        sorted(deployment_ssh_stack_outputs.items())
    )
    routing_text = values["runner_fleet_routing_enabled"]
    if routing_text not in {"false", "true"}:
        raise ValueError("runner-fleet routing intent must be true or false")
    authority = {
        "project": settings.project,
        "deploy_namespace": settings.deploy_namespace,
        "stack_name": runner_fleet_stack_name(settings),
        "aws_capability": aws_capability,
        "aws_region": aws_region,
        "github_capability": values["runner_fleet_github_capability"],
        "repo": values["runner_fleet_repo"],
        "repo_owner": values["runner_fleet_github_repo_owner"],
        "repo_name": values["runner_fleet_github_repo_name"],
        "installation_id": values["runner_fleet_github_installation_id"],
        "repository_id": values["runner_fleet_github_repository_id"],
        "app_issuer": values["runner_fleet_github_app_issuer"],
        "api_url": values["runner_fleet_github_api_url"],
        "web_url": values["runner_fleet_github_web_url"],
        "private_key_secret_arn": values["runner_fleet_github_private_key_secret_arn"],
        "runner_labels": labels,
        "runner_variable_name": values["runner_fleet_variable_name"],
        "routing_enabled": routing_text == "true",
        "runner_count": int(values["runner_fleet_runner_count"]),
        "max_runner_count": int(values["runner_fleet_max_runner_count"]),
        "instance_type": values["runner_fleet_instance_type"],
        "architecture": values["runner_fleet_architecture"],
        "root_volume_gb": int(values["runner_fleet_root_volume_gb"]),
        "idle_shutdown_minutes": int(values["runner_fleet_idle_shutdown_minutes"]),
        "shutdown_mode": values["runner_fleet_shutdown_mode"],
        "deployment_ssh_stack_outputs": deployment_ssh_stack_outputs,
    }
    canonical = json_helper.dumps_compact(dict(sorted(authority.items())))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return json_helper.dumps_compact(
        {
            "schema": 1,
            "authority": authority,
            "sha256": digest,
        }
    )


def authority_intent_from_settings(
    settings: ProjectRendererSettings,
) -> tuple[str, dict[str, str], str, str]:
    """Build the canonical intent and selected AWS authority from settings."""
    values = runner_fleet_values(settings, fallback_repo="", enabled=True)
    raw_runner = settings.capabilities.get(RUNNER_FLEET_CAPABILITY_TYPE)
    selected = (
        validate_runner_fleet_settings(raw_runner)
        if raw_runner
        else RunnerFleetSettings()
    )
    aws_capability = selected.aws_capability
    raw_aws = settings.capabilities.get(aws_capability)
    aws_region = str(raw_aws.get("region") or "").strip() if raw_aws else ""
    if not aws_region:
        raise ValueError(
            "runner-fleet settings snapshot selected AWS capability "
            f"{aws_capability!r} but it declares no region"
        )
    envelope = authority_intent_envelope(
        settings,
        values,
        aws_capability=aws_capability,
        aws_region=aws_region,
    )
    return envelope, values, aws_capability, aws_region


__all__ = ["authority_intent_envelope", "authority_intent_from_settings"]
