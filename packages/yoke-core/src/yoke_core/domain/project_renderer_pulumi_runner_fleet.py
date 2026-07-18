"""Runner-fleet Pulumi render values sourced from project capabilities."""

from __future__ import annotations

import re
from typing import Dict, Mapping

from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    github_web_url_from_api,
    normalize_github_repository,
    validate_github_api_endpoint,
)
from yoke_contracts.github_app_installation_permissions import (
    ACCESS_WRITE,
    ACTIONS_VARIABLES_PERMISSION,
    ADMINISTRATION_PERMISSION,
    REPOSITORY_HOOKS_PERMISSION,
)

from . import json_helper
from .github_app_deployment import (
    GitHubAppDeploymentConfig,
)
from .github_actions_runner_fleet_capability import (
    CAPABILITY_TYPE as RUNNER_FLEET_CAPABILITY_TYPE,
    RunnerFleetSettings,
    validate as validate_runner_fleet_settings,
)
from .project_renderer_settings import (
    PULUMI_STATE_CAPABILITY_TYPE,
    ProjectRendererSettings,
    _stringify,
)
from .project_renderer_runner_deployment_network import (
    deployment_ssh_stack_outputs,
)


def runner_fleet_values(
    settings: ProjectRendererSettings, *, fallback_repo: str, enabled: bool,
) -> Dict[str, str]:
    """Return Pulumi template values for the runner-fleet stack."""
    runner_fleet = _runner_fleet_settings(settings)
    runner_aws = settings.capabilities.get(runner_fleet.aws_capability, {})
    runner_aws_region = _stringify(runner_aws.get("region"))
    if enabled and not runner_aws_region:
        raise ValueError(
            "runner-fleet selected AWS capability "
            f"{runner_fleet.aws_capability!r} but it declares no region"
        )
    github = _github_binding(
        settings,
        capability_selector=runner_fleet.github_capability,
        required=enabled,
    )
    app = _github_app(
        runner_fleet,
        required=enabled,
    )
    bound_repo = _bound_repo(github)
    if enabled and runner_fleet.repo and runner_fleet.repo != bound_repo:
        raise ValueError(
            "runner-fleet capability repo must match the verified GitHub App "
            f"binding ({bound_repo}); remove the stale repo override"
        )
    bound_api_url = _stringify(github.get("api_url"))
    if enabled:
        try:
            bound_api_url = validate_github_api_endpoint(
                bound_api_url
            ).base_url
        except GitHubApiOriginError as exc:
            raise ValueError(
                f"runner-fleet GitHub binding api_url is invalid: {exc}"
            ) from exc
        if app is None or app.api_url != bound_api_url:
            raise ValueError(
                "runner-fleet GitHub App API URL must "
                "match the verified repository binding"
            )
        permissions = github.get("permissions")
        required_permissions = [
            (ADMINISTRATION_PERMISSION, "Administration"),
            (REPOSITORY_HOOKS_PERMISSION, "Webhooks"),
            (ACTIONS_VARIABLES_PERMISSION, "Variables"),
        ]
        missing_permissions = [
            f"{label}: {ACCESS_WRITE} ({key})"
            for key, label in required_permissions
            if not isinstance(permissions, Mapping)
            or str(permissions.get(key) or "").lower() != ACCESS_WRITE
        ]
        if missing_permissions:
            raise ValueError(
                "runner-fleet stack requires verified GitHub App permissions: "
                + ", ".join(missing_permissions)
            )
    api_url = bound_api_url if enabled else (app.api_url if app is not None else "")
    web_url = _web_url_from_api(api_url) if api_url else ""
    resolved_deployment_ssh_stack_outputs = (
        deployment_ssh_stack_outputs(settings, runner_fleet) if enabled else {}
    )
    values = {
        "runner_fleet_aws_capability": runner_fleet.aws_capability,
        "runner_fleet_aws_region": runner_aws_region,
        "runner_fleet_github_capability": runner_fleet.github_capability or "",
        "runner_fleet_repo": bound_repo or _stringify(
            runner_fleet.repo, fallback_repo,
        ),
        "runner_fleet_github_repo_owner": _stringify(github.get("repo_owner")),
        "runner_fleet_github_repo_name": _stringify(github.get("repo_name")),
        "runner_fleet_github_installation_id": _stringify(
            github.get("installation_id")
        ),
        "runner_fleet_github_repository_id": _stringify(
            github.get("repository_id")
        ),
        "runner_fleet_github_app_issuer": app.issuer if app else "",
        "runner_fleet_github_api_url": api_url,
        "runner_fleet_github_web_url": web_url,
        "runner_fleet_github_private_key_secret_arn": (
            app.private_key_secret_arn if app else ""
        ),
        "runner_fleet_token_broker_function": (
            runner_fleet_token_broker_function_name(settings)
        ),
        "runner_fleet_labels_json": json_helper.dumps_compact(
            runner_fleet.runner_labels
        ),
        "runner_fleet_variable_name": runner_fleet.variable_name,
        "runner_fleet_routing_enabled": (
            "true" if runner_fleet.routing_enabled else "false"
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
        "runner_fleet_deployment_ssh_stack_outputs_json": (
            json_helper.dumps_compact(resolved_deployment_ssh_stack_outputs)
        ),
    }
    if enabled:
        _validate_enabled_values(values)
    return values


def runner_fleet_token_broker_function_name(
    settings: ProjectRendererSettings,
) -> str:
    """Return the stable AWS broker function bound into runner authority."""
    return f"{settings.deploy_namespace}-runner-fleet-token-broker"


def runner_fleet_stack_name(settings: ProjectRendererSettings) -> str:
    """Return the exact declared Pulumi state name for the runner stack."""
    pulumi_settings = settings.capabilities.get(PULUMI_STATE_CAPABILITY_TYPE, {})
    configured = _stringify(pulumi_settings.get("runner_fleet_stack_name"))
    return configured or f"{settings.deploy_namespace}-runner-fleet"


def _runner_fleet_settings(
    settings: ProjectRendererSettings,
) -> RunnerFleetSettings:
    raw = settings.capabilities.get(RUNNER_FLEET_CAPABILITY_TYPE)
    if raw:
        return validate_runner_fleet_settings(raw)
    return RunnerFleetSettings()


def _github_binding(
    settings: ProjectRendererSettings,
    *,
    capability_selector: str | None,
    required: bool,
) -> Dict[str, object]:
    if not capability_selector:
        if required:
            raise ValueError(
                "runner-fleet stack requires explicit github_capability in "
                "the github-actions-runner-fleet capability settings"
            )
        return {}
    github = settings.capabilities.get(capability_selector, {})
    missing = [
        key for key in (
            "repo_owner", "repo_name", "installation_id", "repository_id",
            "api_url",
        )
        if not _stringify(github.get(key))
    ]
    if required and missing:
        raise ValueError(
            "runner-fleet stack requires a verified GitHub App repository "
            f"binding; selected {capability_selector!r} capability is missing "
            "settings: " + ", ".join(missing)
        )
    return github


def _github_app(
    runner_fleet: RunnerFleetSettings,
    *,
    required: bool,
) -> GitHubAppDeploymentConfig | None:
    if not required:
        return None
    if runner_fleet.github_app is None:
        raise ValueError(
            "runner-fleet stack requires github_app in the "
            "github-actions-runner-fleet capability settings"
        )
    return GitHubAppDeploymentConfig(
        issuer=runner_fleet.github_app.issuer,
        api_url=runner_fleet.github_app.api_url,
        private_key_secret_arn=runner_fleet.github_app.private_key_secret_arn,
    )


def _bound_repo(github: Dict[str, object]) -> str:
    owner = _stringify(github.get("repo_owner"))
    name = _stringify(github.get("repo_name"))
    if not owner or not name:
        return ""
    try:
        return normalize_github_repository(f"{owner}/{name}")
    except GitHubApiOriginError as exc:
        raise ValueError(f"runner-fleet GitHub repository binding is invalid: {exc}") from exc


def _web_url_from_api(api_url: str) -> str:
    return github_web_url_from_api(api_url)


def _validate_enabled_values(values: Dict[str, str]) -> None:
    for key in (
        "runner_fleet_github_installation_id",
        "runner_fleet_github_repository_id",
    ):
        if re.fullmatch(r"[1-9][0-9]*", values[key]) is None:
            raise ValueError(f"{key} must be a positive GitHub numeric id")
    secret_arn = values["runner_fleet_github_private_key_secret_arn"]
    if re.fullmatch(
        r"arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:"
        r"[A-Za-z0-9/_+=.@-]+",
        secret_arn,
    ) is None:
        raise ValueError(
            "runner-fleet github_app."
            "private_key_secret_arn must be a complete AWS Secrets Manager ARN"
        )
