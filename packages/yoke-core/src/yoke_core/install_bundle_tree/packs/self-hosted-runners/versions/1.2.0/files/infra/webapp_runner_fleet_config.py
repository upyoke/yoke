"""Validated input shape for the runner-fleet Pulumi component."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

#: Runners are disposable, so the fleet rides spot capacity by default: no
#: on-demand floor, and nothing above that floor bought on demand either.
DEFAULT_SPOT_ON_DEMAND_BASE_CAPACITY = 0
DEFAULT_SPOT_ON_DEMAND_PERCENTAGE_ABOVE_BASE = 0


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
    #: How many runners are held on on-demand capacity before spot is used at
    #: all. Runners are disposable — an interrupted one fails a job that reruns
    #: — so this is normally 0 and the whole fleet rides spot. Raise it to keep
    #: a floor of runners that a spot shortage cannot take away.
    spot_on_demand_base_capacity: int = DEFAULT_SPOT_ON_DEMAND_BASE_CAPACITY
    #: Percent of capacity ABOVE that base bought on demand. 0 means the rest
    #: of the fleet is entirely spot.
    spot_on_demand_percentage_above_base: int = (
        DEFAULT_SPOT_ON_DEMAND_PERCENTAGE_ABOVE_BASE
    )


def validate_runner_fleet_configuration(args: WebappRunnerFleetArgs) -> None:
    """Refuse unsupported fleet shapes before creating any resources."""
    if args.shutdown_mode != "terminate":
        raise ValueError("runner fleet v1 supports shutdown_mode=terminate")
    if args.runner_count < 1:
        raise ValueError("runner_count must be positive")
    if args.max_runner_count < args.runner_count:
        raise ValueError(
            "max_runner_count must be greater than or equal to runner_count"
        )
    if args.spot_on_demand_base_capacity < 0:
        raise ValueError("spot_on_demand_base_capacity must not be negative")
    if args.spot_on_demand_base_capacity > args.max_runner_count:
        raise ValueError(
            "spot_on_demand_base_capacity must not exceed max_runner_count"
        )
    if not 0 <= args.spot_on_demand_percentage_above_base <= 100:
        raise ValueError(
            "spot_on_demand_percentage_above_base must be between 0 and 100"
        )


__all__ = [
    "DEFAULT_SPOT_ON_DEMAND_BASE_CAPACITY",
    "DEFAULT_SPOT_ON_DEMAND_PERCENTAGE_ABOVE_BASE",
    "WebappRunnerFleetArgs",
    "validate_runner_fleet_configuration",
]
