"""Read the runner-fleet stack's inputs from its config.

Every fleet input is a fact Yoke validates on the project's
``github-actions-runner-fleet`` capability and its verified GitHub App
binding, plus the Yoke project slug the authority-intent check compares. ``yoke pulumi exec`` passes them as ``yoke:runner_fleet_*``
values only when the stack file sets ``yoke:github_access: runner_fleet``;
without that level each read below fails with Pulumi's missing-config error
naming the ``yoke:`` key.
"""

from __future__ import annotations

import json

import pulumi

from webapp_runner_fleet_config import WebappRunnerFleetArgs


def runner_fleet_args_from_config(deploy_namespace: str) -> WebappRunnerFleetArgs:
    """Build the fleet inputs from the stack's ``yoke:runner_fleet_*`` values."""
    yoke = pulumi.Config("yoke")

    def text(key: str) -> str:
        return yoke.require(f"runner_fleet_{key}")

    def number(key: str) -> int:
        return yoke.require_int(f"runner_fleet_{key}")

    def flag(key: str) -> bool:
        return yoke.require_bool(f"runner_fleet_{key}")

    return WebappRunnerFleetArgs(
        project=text("project"),
        deploy_namespace=deploy_namespace,
        aws_capability=text("aws_capability"),
        aws_region=text("aws_region"),
        github_capability=text("github_capability"),
        github_repo=text("repo"),
        github_repo_owner=text("github_repo_owner"),
        github_repo_name=text("github_repo_name"),
        github_installation_id=text("github_installation_id"),
        github_repository_id=text("github_repository_id"),
        github_app_issuer=text("github_app_issuer"),
        github_api_url=text("github_api_url"),
        github_web_url=text("github_web_url"),
        github_private_key_secret_arn=text("github_private_key_secret_arn"),
        token_broker_function=text("token_broker_function"),
        runner_labels=_string_list(text("labels_json"), "labels_json"),
        runner_variable_name=text("variable_name"),
        routing_enabled=flag("routing_enabled"),
        lifecycle_writers_paused=flag("lifecycle_writers_paused"),
        lifecycle_code_frozen=flag("lifecycle_code_frozen"),
        runner_count=number("runner_count"),
        max_runner_count=number("max_runner_count"),
        instance_type=text("instance_type"),
        architecture=text("architecture"),
        root_volume_gb=number("root_volume_gb"),
        idle_shutdown_minutes=number("idle_shutdown_minutes"),
        shutdown_mode=text("shutdown_mode"),
        spot_on_demand_base_capacity=number("spot_on_demand_base_capacity"),
        spot_on_demand_percentage_above_base=number(
            "spot_on_demand_percentage_above_base"
        ),
        deployment_ssh_stack_outputs=_string_map(
            text("deployment_ssh_stack_outputs_json"),
            "deployment_ssh_stack_outputs_json",
        ),
    )


def _loaded(raw: str, key: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise pulumi.RunError(f"yoke:runner_fleet_{key} is not JSON: {exc}") from exc


def _string_list(raw: str, key: str) -> list[str]:
    values = _loaded(raw, key)
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise pulumi.RunError(f"yoke:runner_fleet_{key} must be a JSON string array")
    return [value.strip() for value in values]


def _string_map(raw: str, key: str) -> dict[str, str]:
    values = _loaded(raw, key)
    if not isinstance(values, dict) or any(
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(value, str)
        or not value.strip()
        for name, value in values.items()
    ):
        raise pulumi.RunError(f"yoke:runner_fleet_{key} must be a JSON string map")
    return {name.strip(): value.strip() for name, value in values.items()}


__all__ = ["runner_fleet_args_from_config"]
