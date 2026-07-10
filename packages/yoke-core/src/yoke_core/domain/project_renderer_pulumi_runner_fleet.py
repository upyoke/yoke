"""Runner-fleet Pulumi render values sourced from project capabilities."""

from __future__ import annotations

import re
from typing import Dict, Mapping
import urllib.parse

from yoke_contracts.github_origin import (
    DEFAULT_GITHUB_API_URL,
    DEFAULT_GITHUB_WEB_URL,
    GitHubApiOriginError,
    normalize_github_repository,
    validate_github_api_endpoint,
    validate_github_endpoint_pair,
)

from . import json_helper
from .github_app_deployment import (
    GitHubAppDeploymentConfig,
    GitHubAppDeploymentConfigError,
    github_app_config_from_environment_settings,
)
from .github_actions_runner_fleet_capability import (
    CAPABILITY_TYPE as RUNNER_FLEET_CAPABILITY_TYPE,
    RunnerFleetSettings,
    validate as validate_runner_fleet_settings,
)
from .project_renderer_settings import ProjectRendererSettings, _stringify


def runner_fleet_values(
    settings: ProjectRendererSettings, *, fallback_repo: str, enabled: bool,
) -> Dict[str, str]:
    """Return Pulumi template values for the runner-fleet stack."""
    runner_fleet = _runner_fleet_settings(settings)
    github = _github_binding(settings, required=enabled)
    app = _github_app(settings, required=enabled)
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
                "runner-fleet primary environment GitHub App API URL must "
                "match the verified repository binding"
            )
        permissions = github.get("permissions")
        if (
            not isinstance(permissions, Mapping)
            or str(permissions.get("administration") or "").lower() != "write"
        ):
            raise ValueError(
                "runner-fleet stack requires verified GitHub App "
                "administration: write permission"
            )
    api_url = bound_api_url if enabled else (app.api_url if app is not None else "")
    web_url = _web_url_from_api(api_url) if api_url else ""
    values = {
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
        "runner_fleet_labels_json": json_helper.dumps_compact(
            runner_fleet.runner_labels
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
    }
    if enabled:
        _validate_enabled_values(values)
    return values


def _runner_fleet_settings(
    settings: ProjectRendererSettings,
) -> RunnerFleetSettings:
    raw = settings.capabilities.get(RUNNER_FLEET_CAPABILITY_TYPE)
    if raw:
        return validate_runner_fleet_settings(raw)
    return RunnerFleetSettings()


def _github_binding(
    settings: ProjectRendererSettings, *, required: bool,
) -> Dict[str, object]:
    github = settings.capabilities.get("github", {})
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
            "binding; missing github capability settings: " + ", ".join(missing)
        )
    return github


def _github_app(
    settings: ProjectRendererSettings, *, required: bool,
) -> GitHubAppDeploymentConfig | None:
    environment = settings.primary_environment
    if environment is None:
        if required:
            raise ValueError(
                "runner-fleet stack requires a primary environment with "
                "settings.github_app"
            )
        return None
    try:
        app = github_app_config_from_environment_settings(
            environment.settings,
            env_hint=f"environment {environment.name!r}",
        )
    except GitHubAppDeploymentConfigError as exc:
        if not required:
            return None
        raise ValueError(f"runner-fleet GitHub App configuration is invalid: {exc}") from exc
    if required and app is None:
        raise ValueError(
            "runner-fleet stack requires primary environment "
            "settings.github_app with issuer, api_url, and "
            "private_key_secret_arn"
        )
    return app


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
    endpoint = validate_github_api_endpoint(api_url)
    parsed = urllib.parse.urlsplit(endpoint.base_url)
    hostname = str(parsed.hostname or "")
    if endpoint.base_url == DEFAULT_GITHUB_API_URL:
        web_url = DEFAULT_GITHUB_WEB_URL
    elif hostname.startswith("api.") and hostname.endswith(".ghe.com"):
        authority = hostname.removeprefix("api.")
        if parsed.port is not None:
            authority = f"{authority}:{parsed.port}"
        web_url = f"https://{authority}"
    elif parsed.path.rstrip("/") == "/api/v3":
        web_url = endpoint.origin
    else:
        raise ValueError(
            "runner-fleet GitHub API URL must be a canonical GitHub Cloud, "
            "GitHub Enterprise Cloud data-residency, or GHES base"
        )
    return validate_github_endpoint_pair(api_url, web_url).web.base_url


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
            "runner-fleet primary environment github_app."
            "private_key_secret_arn must be a complete AWS Secrets Manager ARN"
        )
