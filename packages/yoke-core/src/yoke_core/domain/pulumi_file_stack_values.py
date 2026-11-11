"""Yoke-owned Pulumi config values and authority for a file-backed stack.

A file-backed stack keeps its own settings in the project's checked-in
``infra/Pulumi.<stack>.yaml``. Yoke adds only the values it computes or
relies on for its own logic and authority, under the reserved ``yoke:``
config namespace, so a program reads them with ``pulumi.Config("yoke")``.
Nothing project-specific is forwarded and no default is invented: a value
Yoke does not hold is left out, and a program that needs it fails with
Pulumi's own missing-config error naming the ``yoke:`` key.

Values come from the project's renderer settings, which both the local
database and the hosted secret-free settings snapshot serve, so this path
needs no stack declaration, stored stack state or server change.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import json_helper
from yoke_core.domain.github_actions_runner_fleet_capability import (
    CAPABILITY_TYPE as RUNNER_FLEET_CAPABILITY_TYPE,
)
from yoke_core.domain.project_renderer_pulumi_ci import delivery_ci_values
from yoke_core.domain.project_renderer_pulumi_runner_fleet import (
    runner_fleet_values,
)
from yoke_core.domain.project_renderer_settings import (
    PULUMI_STATE_CAPABILITY_TYPE,
    ProjectRendererSettings,
    _first_mapping,
)
from yoke_core.domain.pulumi_state_capability import COMPONENT_TYPE_ALIASES_KEY
from yoke_core.domain.repository_provider_authority import (
    repository_provider_intent_from_settings,
)


#: Reserved Pulumi config namespace for Yoke-owned values.
YOKE_CONFIG_NAMESPACE = "yoke"
#: The one ``yoke:`` key a stack file may set: its GitHub access level.
GITHUB_ACCESS_KEY = "github_access"
METADATA_ACCESS = "metadata"
VARIABLES_ACCESS = "variables"
RUNNER_FLEET_ACCESS = "runner_fleet"
#: GitHub App permissions each access level grants, least first.
GITHUB_ACCESS_PERMISSIONS: Mapping[str, Mapping[str, str]] = {
    METADATA_ACCESS: {"metadata": "read"},
    VARIABLES_ACCESS: {"metadata": "read", "actions_variables": "write"},
    RUNNER_FLEET_ACCESS: {
        "metadata": "read",
        "actions_variables": "write",
        "repository_hooks": "write",
    },
}
AWS_CAPABILITY_TYPE = "aws-admin"


class FileStackValuesError(ValueError):
    """Yoke cannot supply the values or authority a file-backed stack needs."""


def file_stack_yoke_values(
    settings: ProjectRendererSettings, stack: str, github_access: str
) -> dict[str, str]:
    """Return the Yoke-owned ``yoke:`` values for one file-backed stack."""
    _require_access(github_access)
    aws = _first_mapping(settings.capabilities.get(AWS_CAPABILITY_TYPE))
    state = _first_mapping(settings.capabilities.get(PULUMI_STATE_CAPABILITY_TYPE))
    github = _first_mapping(settings.capabilities.get("github"))
    owner = _text(github.get("repo_owner"))
    repo = _text(github.get("repo_name"))
    ci = delivery_ci_values(
        settings, required_keys={"github_api_url", "delivery_authority_json"}
    )
    values = {
        "aws_account_id": _text(aws.get("account_id")),
        "aws_region": _text(aws.get("region")),
        "deploy_namespace": _text(settings.deploy_namespace),
        "kms_key_alias": _text(state.get("kms_key_alias")),
        "github_repo_slug": f"{owner}/{repo}" if owner and repo else "",
        "github_api_url": _text(ci.get("github_api_url")),
        "delivery_authority_json": _text(ci.get("delivery_authority_json")),
        "component_type_aliases_json": json_helper.dumps_compact(
            state.get(COMPONENT_TYPE_ALIASES_KEY) or {}
        ),
    }
    if github_access == RUNNER_FLEET_ACCESS:
        try:
            values.update(runner_fleet_values(
                settings, fallback_repo=values["github_repo_slug"], enabled=True
            ))
            values["runner_fleet_project"] = settings.project
        except ValueError as exc:
            raise FileStackValuesError(
                f"pulumi_runner_fleet_values_unavailable: {exc}; repair the "
                "project's runner-fleet capability, or set the stack file's "
                f"{YOKE_CONFIG_NAMESPACE}:{GITHUB_ACCESS_KEY} to a lower level"
            ) from exc
    values.update(_environment_facts(settings, stack))
    return {key: value for key, value in sorted(values.items()) if value}


def file_stack_authority(
    settings: ProjectRendererSettings,
    values: Mapping[str, str],
    github_access: str,
) -> dict[str, Any]:
    """Return the AWS, backend and GitHub authority for one file-backed stack."""
    permissions = _require_access(github_access)
    aws = _first_mapping(settings.capabilities.get(AWS_CAPABILITY_TYPE))
    state = _first_mapping(settings.capabilities.get(PULUMI_STATE_CAPABILITY_TYPE))
    region = _text(aws.get("region"))
    state_bucket = _text(state.get("state_bucket"))
    if not region or not state_bucket:
        raise FileStackValuesError(
            "pulumi_backend_authority_missing: a file-backed stack needs the "
            f"{AWS_CAPABILITY_TYPE} capability region and the "
            f"{PULUMI_STATE_CAPABILITY_TYPE} capability state_bucket; set them "
            "with `yoke projects capability` and retry"
        )
    runner_fleet = github_access == RUNNER_FLEET_ACCESS
    repo = _text(values.get("runner_fleet_repo" if runner_fleet else "github_repo_slug"))
    api_url = _text(
        values.get("runner_fleet_github_api_url" if runner_fleet else "github_api_url")
    )
    authority: dict[str, Any] = {
        "aws_capability": AWS_CAPABILITY_TYPE,
        "aws_region": region,
        "backend_url": f"s3://{state_bucket}?region={region}",
        "github_project": settings.project,
        "github_repo": repo,
        "github_api_url": api_url if repo else "",
        "github_permissions": dict(permissions),
    }
    if (
        repo
        and github_access == VARIABLES_ACCESS
        and RUNNER_FLEET_CAPABILITY_TYPE in settings.capabilities
    ):
        try:
            authority["hosted_repository_token_intent"] = (
                repository_provider_intent_from_settings(
                    settings, expected_repo=repo
                )
            )
        except ValueError as exc:
            raise FileStackValuesError(
                f"pulumi_repository_provider_unavailable: {exc}; repair the "
                "project's runner-fleet capability and retry"
            ) from exc
    return authority


def _environment_facts(
    settings: ProjectRendererSettings, stack: str
) -> dict[str, str]:
    """Facts Yoke holds for the environment whose Pulumi stack this is."""
    for environment in settings.environments:
        env = environment.settings
        pulumi = _first_mapping(env.get("pulumi"))
        if _text(pulumi.get("stack_name")) != stack:
            continue
        hosts = _first_mapping(env.get("hosts"))
        database = _first_mapping(env.get("database"))
        distribution = _first_mapping(env.get("distribution"))
        github_app = _first_mapping(env.get("github_app"))
        return {
            "environment": _text(environment.name),
            "api_host": _text(hosts.get("api")),
            "origin_host": _text(hosts.get("origin")),
            "api_origin_port": _text(hosts.get("origin_port")),
            "origin_vps_stack_name": _text(pulumi.get("origin_vps_stack_name")),
            "database_name": _text(database.get("name")),
            "distribution_bucket_name": _text(distribution.get("bucket_name")),
            "distribution_origin_id": _text(distribution.get("origin_id")),
            "distribution_base_url": _text(distribution.get("base_url")),
            "github_app_private_key_secret_arn": _text(
                github_app.get("private_key_secret_arn")
            ),
            "github_app_kms_key_arn": _text(github_app.get("kms_key_arn")),
            "ephemeral_preview_domain": _preview_domain(settings, environment),
        }
    return {}


def _preview_domain(settings: ProjectRendererSettings, environment: Any) -> str:
    previews = _first_mapping(environment.settings.get("previews"))
    if _text(previews.get("domain")):
        return _text(previews.get("domain"))
    ephemeral = _first_mapping(settings.capabilities.get("ephemeral-env"))
    if _text(ephemeral.get("host_env")) == environment.name:
        return _text(ephemeral.get("preview_domain"))
    return ""


def _require_access(github_access: str) -> Mapping[str, str]:
    permissions = GITHUB_ACCESS_PERMISSIONS.get(github_access)
    if permissions is None:
        raise FileStackValuesError(
            f"pulumi_github_access_unknown: {YOKE_CONFIG_NAMESPACE}:"
            f"{GITHUB_ACCESS_KEY} is {github_access!r}; use one of "
            f"{', '.join(GITHUB_ACCESS_PERMISSIONS)} or leave it unset for "
            f"{METADATA_ACCESS}"
        )
    return permissions


def _text(value: object) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


__all__ = [
    "FileStackValuesError",
    "GITHUB_ACCESS_KEY",
    "GITHUB_ACCESS_PERMISSIONS",
    "METADATA_ACCESS",
    "RUNNER_FLEET_ACCESS",
    "VARIABLES_ACCESS",
    "YOKE_CONFIG_NAMESPACE",
    "file_stack_authority",
    "file_stack_yoke_values",
]
