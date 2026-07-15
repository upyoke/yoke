# AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_fleet_config.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Validated input shape for the runner-fleet Pulumi component."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass
class WebappRunnerFleetArgs:
    """Inputs for ``WebappRunnerFleetStack``."""

    project: str
    deploy_namespace: str
    aws_capability: str
    aws_region: str
    github_capability: str
    github_repo: str
    github_repo_owner: str
    github_repo_name: str
    github_installation_id: str
    github_repository_id: str
    github_app_issuer: str
    github_api_url: str
    github_web_url: str
    github_private_key_secret_arn: str
    token_broker_function: str
    runner_labels: Sequence[str]
    runner_variable_name: str
    routing_enabled: bool
    runner_count: int
    max_runner_count: int
    instance_type: str
    architecture: str
    root_volume_gb: int
    idle_shutdown_minutes: int
    shutdown_mode: str
    deployment_ssh_stack_outputs: Mapping[str, str]


def validate_runner_fleet_configuration(args: WebappRunnerFleetArgs) -> None:
    """Refuse unsupported fleet shapes before creating any resources."""
    if args.shutdown_mode != "terminate":
        raise ValueError("runner fleet v1 supports shutdown_mode=terminate")
    if args.runner_count != 1 or args.max_runner_count != 1:
        raise ValueError("runner fleet v1 requires one ephemeral runner per host")


__all__ = ["WebappRunnerFleetArgs", "validate_runner_fleet_configuration"]
