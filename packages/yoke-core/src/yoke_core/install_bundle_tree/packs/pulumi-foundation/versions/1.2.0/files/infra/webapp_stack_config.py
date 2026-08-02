"""Validated collection values shared by composed Pulumi stacks."""

import pulumi


def config_string_list(config, name: str) -> list[str]:
    values = config.get_object(name) or []
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise pulumi.RunError(f"{name} must be a JSON string array")
    return [value.strip() for value in values]


def config_string_map(config, name: str) -> dict[str, str]:
    values = config.get_object(name) or {}
    if not isinstance(values, dict) or any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(value, str)
        or not value.strip()
        for key, value in values.items()
    ):
        raise pulumi.RunError(f"{name} must be a JSON string map")
    return {key.strip(): value.strip() for key, value in values.items()}


__all__ = ["config_string_list", "config_string_map"]


def config_int_or_default(config, key: str, default: int) -> int:
    """Read an optional integer stack setting, falling back to ``default``."""
    value = config.get_int(key)
    return default if value is None else value


def runner_fleet_args_from_config(deploy_namespace: str):
    from webapp_runner_fleet_config import (
        DEFAULT_SPOT_ON_DEMAND_BASE_CAPACITY,
        DEFAULT_SPOT_ON_DEMAND_PERCENTAGE_ABOVE_BASE,
        WebappRunnerFleetArgs,
    )

    config = pulumi.Config()
    aws_config = pulumi.Config("aws")
    labels = json.loads(config.require("runner_labels"))
    return WebappRunnerFleetArgs(
        project=config.require("project_name"),
        deploy_namespace=deploy_namespace,
        aws_capability=config.require("aws_capability"),
        aws_region=aws_config.require("region"),
        github_capability=config.require("github_capability"),
        github_repo=config.require("github_repo"),
        github_repo_owner=config.require("github_repo_owner"),
        github_repo_name=config.require("github_repo_name"),
        github_installation_id=config.require("github_installation_id"),
        github_repository_id=config.require("github_repository_id"),
        github_app_issuer=config.require("github_app_issuer"),
        github_api_url=config.require("github_api_url"),
        github_web_url=config.require("github_web_url"),
        github_private_key_secret_arn=config.require("github_private_key_secret_arn"),
        token_broker_function=config.require("token_broker_function"),
        runner_labels=[str(label) for label in labels],
        runner_variable_name=config.require("runner_variable_name"),
        routing_enabled=config.require_bool("routing_enabled"),
        runner_count=config.require_int("runner_count"),
        max_runner_count=config.require_int("max_runner_count"),
        instance_type=config.require("instance_type"),
        architecture=config.require("architecture"),
        root_volume_gb=config.require_int("root_volume_gb"),
        idle_shutdown_minutes=config.require_int("idle_shutdown_minutes"),
        shutdown_mode=config.require("shutdown_mode"),
        # Optional so a stack whose config predates spot support still loads;
        # the defaults put the whole fleet on spot.
        spot_on_demand_base_capacity=config_int_or_default(
            config,
            "spot_on_demand_base_capacity",
            DEFAULT_SPOT_ON_DEMAND_BASE_CAPACITY,
        ),
        spot_on_demand_percentage_above_base=config_int_or_default(
            config,
            "spot_on_demand_percentage_above_base",
            DEFAULT_SPOT_ON_DEMAND_PERCENTAGE_ABOVE_BASE,
        ),
        deployment_ssh_stack_outputs=config_string_map(
            config, "deployment_ssh_stack_outputs"
        ),
    )
