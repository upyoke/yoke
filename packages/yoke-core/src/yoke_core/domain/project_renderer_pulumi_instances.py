"""Pulumi stack-instance parsing for project-owned Pack renders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yoke_core.domain import json_helper

from .project_renderer_runner_deployment_network import (
    STANDALONE_VPS_ELASTIC_IP_OUTPUT,
    STANDALONE_VPS_SECURITY_GROUP_OUTPUT,
)
from .project_renderer_settings import (
    ProjectRendererSettings,
    _first_mapping,
    load_project_renderer_settings,
    primary_domain,
)

DEFAULT_DATABASE_SECONDS_UNTIL_AUTO_PAUSE = "1800"


@dataclass(frozen=True)
class PulumiStackInstance:
    name: str
    environment: str
    capabilities: tuple[str, ...]
    config: dict[str, str]
    render_only: bool


def gather_pulumi_stack_instances(
    project: str,
    project_root: Path,
    settings: ProjectRendererSettings | None = None,
) -> list[PulumiStackInstance]:
    """Read stack instances from DB-backed environment settings."""
    del project_root
    if settings is None:
        settings = load_project_renderer_settings(project)
    return pulumi_stack_instances_from_settings(settings)


def pulumi_stack_instances_from_settings(
    settings: ProjectRendererSettings,
) -> list[PulumiStackInstance]:
    """Build Pulumi stack instances from ``environments.settings`` rows."""
    raw_instances = [
        raw
        for raw in (
            _raw_stack_instance_from_environment(settings, env)
            for env in settings.environments
        )
        if raw is not None
    ]
    return [
        _parse_stack_instance(settings.project, index, raw)
        for index, raw in enumerate(raw_instances, start=1)
    ]


def _raw_stack_instance_from_environment(
    settings: ProjectRendererSettings,
    env,
) -> dict[str, object] | None:
    pulumi = _first_mapping(env.settings.get("pulumi"))
    stack_name = pulumi.get("stack_name")
    if not stack_name:
        return None
    origin_vps_stack_name = str(
        pulumi.get("origin_vps_stack_name", "") or ""
    ).strip()
    if not origin_vps_stack_name:
        raise ValueError(
            f"Environment {env.name!r} pulumi.origin_vps_stack_name for "
            f"{settings.project} is required: it names the standalone VPS Pulumi "
            "stack whose exported outputs serve this environment's origin. Set it "
            "via: yoke projects environment-settings merge --project "
            f"{settings.project} --environment-id {env.id} --set "
            "pulumi.origin_vps_stack_name=<standalone-vps-stack-name>"
        )

    hosts = _first_mapping(env.settings.get("hosts"))
    database = _first_mapping(env.settings.get("database"))
    distribution = _first_mapping(env.settings.get("distribution"))
    github_app = _first_mapping(env.settings.get("github_app"))
    domain = primary_domain(settings)
    activation_state = str(pulumi.get("activation_state", "") or "")
    render_only = bool(pulumi.get("render_only")) or activation_state == "render_only"
    distribution_bucket_name = str(distribution.get("bucket_name", "") or "")
    distribution_origin_id = str(distribution.get("origin_id", "") or "")
    distribution_variable_namespace = str(
        distribution.get("repository_variable_namespace", "") or ""
    )
    if distribution_bucket_name and not distribution_variable_namespace:
        raise ValueError(
            f"Environment {env.name!r} distribution.repository_variable_namespace "
            f"for {settings.project} is required when distribution publishing is enabled."
        )
    if distribution_bucket_name and not distribution_origin_id:
        distribution_origin_id = _default_distribution_origin_id(
            settings.deploy_namespace,
            env.name,
        )

    config = {
        "api_host": hosts.get("api", ""),
        "origin_host": hosts.get("origin", ""),
        "hosted_zone_id": domain.get("hosted_zone_id", ""),
        "api_origin_port": hosts.get("origin_port", ""),
        "origin_vps_stack_name": origin_vps_stack_name,
        "origin_vps_elastic_ip_output": STANDALONE_VPS_ELASTIC_IP_OUTPUT,
        "origin_vps_security_group_output": STANDALONE_VPS_SECURITY_GROUP_OUTPUT,
        "database_name": database.get("name", ""),
        "database_master_username": database.get("master_username", ""),
        "database_engine_version": database.get("engine_version", ""),
        "database_min_capacity_acu": database.get("min_capacity_acu", ""),
        "database_max_capacity_acu": database.get("max_capacity_acu", ""),
        "database_seconds_until_auto_pause": database.get(
            "seconds_until_auto_pause",
            DEFAULT_DATABASE_SECONDS_UNTIL_AUTO_PAUSE,
        ),
        "database_backup_retention_days": database.get("backup_retention_days", ""),
        "database_allowed_security_group_ids": _json_string_list(
            settings.project,
            env.name,
            "database.allowed_security_group_ids",
            database.get("allowed_security_group_ids", []),
        ),
        "distribution_bucket_name": distribution_bucket_name,
        "distribution_origin_id": distribution_origin_id,
        "distribution_base_url": str(distribution.get("base_url", "") or ""),
        "distribution_repository_variable_namespace": (
            distribution_variable_namespace
        ),
        "ephemeral_preview_domain": _ephemeral_preview_domain(settings, env),
        "github_app_private_key_secret_arn": github_app.get(
            "private_key_secret_arn", ""
        ),
        "github_app_kms_key_arn": github_app.get("kms_key_arn", ""),
    }
    capabilities = env.settings.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    return {
        "name": stack_name,
        "environment": env.name,
        "capabilities": capabilities,
        "config": config,
        "renderOnly": render_only,
    }


def _ephemeral_preview_domain(settings: ProjectRendererSettings, env) -> str:
    """Wildcard preview domain when *env* hosts the project's ephemerals."""
    cap = settings.capabilities.get("ephemeral-env", {})
    if (
        isinstance(cap, dict)
        and str(cap.get("host_env") or "") == env.name
        and cap.get("preview_domain")
    ):
        return str(cap["preview_domain"])
    return ""


def _default_distribution_origin_id(deploy_namespace: str, environment: str) -> str:
    return f"{deploy_namespace}-{environment}-distribution-static"


def _json_string_list(
    project: str,
    environment: str,
    setting: str,
    value: object,
) -> str:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(
            f"Environment {environment!r} {setting} for {project} must be "
            "a list of non-empty strings."
        )
    return json_helper.dumps_compact([item.strip() for item in value])


def instance_template_values(
    instance: PulumiStackInstance,
    values: Mapping[str, str],
) -> dict[str, str]:
    """Build render-template values for one environment stack instance."""
    result = dict(values)
    result.update(instance.config)
    result.update(
        {
            "stack_instance_name": instance.name,
            "stack_name": instance.name,
            "environment": instance.environment,
            "capabilities": ",".join(instance.capabilities),
            "render_only": "true" if instance.render_only else "false",
        }
    )
    return result


def _parse_stack_instance(
    project: str,
    index: int,
    raw: object,
) -> PulumiStackInstance:
    if not isinstance(raw, dict):
        raise ValueError(
            f"Pulumi stackInstances[{index}] for {project} must be an object."
        )

    name = _required_string(project, index, raw, "name")
    environment = _required_string(project, index, raw, "environment")
    capabilities = _string_tuple(project, index, raw.get("capabilities", []))
    config = _string_dict(project, index, raw.get("config", {}), "config")
    render_only = bool(raw.get("renderOnly", False))

    return PulumiStackInstance(
        name=name,
        environment=environment,
        capabilities=capabilities,
        config=config,
        render_only=render_only,
    )


def _required_string(
    project: str,
    index: int,
    raw: Mapping[str, object],
    key: str,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Pulumi stackInstances[{index}].{key} for {project} "
            "must be a non-empty string."
        )
    return value


def _string_tuple(project: str, index: int, value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(
            f"Pulumi stackInstances[{index}].capabilities for {project} must be a list."
        )
    return tuple(str(item) for item in value)


def _string_dict(
    project: str,
    index: int,
    value: object,
    key: str,
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(
            f"Pulumi stackInstances[{index}].{key} for {project} must be an object."
        )
    return {str(k): _config_value_to_string(v) for k, v in value.items()}


def _config_value_to_string(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
