"""Stack-scoped Pulumi renderer materialization from project authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_core.domain.project_github_binding_payload import normalize_github_repo
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.project_renderer_pulumi import (
    _domain_mx_records_json,
    _domain_txt_records_json,
    gather_pulumi_values,
)
from yoke_core.domain.project_renderer_pulumi_context import (
    _pulumi_context_from_settings,
)
from yoke_core.domain.project_renderer_pulumi_instances import (
    gather_pulumi_stack_instances,
    instance_template_values,
)
from yoke_core.domain.project_renderer_pulumi_selection import (
    select_pulumi_targets,
)
from yoke_core.domain.project_renderer_pulumi_stack_types import (
    gather_pulumi_stacks,
)
from yoke_core.domain.project_renderer_settings import (
    PULUMI_STATE_CAPABILITY_TYPE,
    _first_mapping,
    _load_project_renderer_settings,
)
from yoke_core.domain.pulumi_state_capability import validate_stack_state


STACK_CONFIG_SCHEMA = 2
_GITHUB_METADATA_INTENT = {"metadata": "read"}
_GITHUB_VARIABLES_INTENT = {
    "metadata": "read",
    "actions_variables": "write",
}
_RUNNER_FLEET_GITHUB_INTENT = {
    "metadata": "read",
    "actions_variables": "write",
    "repository_hooks": "write",
}
_BASE_STACK_KEYS = frozenset({
    "aws_account_id", "aws_region", "certificate_arn", "deploy_namespace",
    "distribution_bucket_name", "domain_mx_records_json", "domain_name",
    "domain_txt_records_json", "hosted_zone_id", "kms_key_alias",
    "origin_host", "origin_id", "vps_iam_instance_profile_name",
    "vps_instance_type", "vps_root_volume_gb", "vps_ssh_key_name",
})
_RENDER_KEYS_BY_KIND = {
    "infra": _BASE_STACK_KEYS,
    "vps": _BASE_STACK_KEYS,
    "domain": frozenset({
        "aws_account_id", "aws_region", "deploy_namespace",
        "domain_mx_records_json", "domain_name", "domain_txt_records_json",
        "import_zone_id", "manage_registration",
    }),
    "registry": frozenset({
        "aws_account_id", "aws_region", "delivery_distribution_bucket_names_json",
        "deploy_namespace", "github_api_url",
        "github_app_private_key_secret_arns_json", "github_repo_slug",
        "kms_key_alias", "manage_github_oidc_provider", "repository_name",
        "state_bucket",
    }),
    "environment": frozenset({
        "api_host", "api_origin_port", "aws_account_id", "aws_region",
        "capabilities", "database_allowed_security_group_ids",
        "database_backup_retention_days", "database_engine_version",
        "database_master_username", "database_max_capacity_acu",
        "database_min_capacity_acu", "database_name",
        "database_seconds_until_auto_pause", "deploy_namespace",
        "distribution_base_url", "distribution_bucket_name",
        "distribution_origin_id", "distribution_repository_variable_namespace",
        "domain_name", "environment", "ephemeral_preview_domain",
        "github_api_url", "github_app_kms_key_arn",
        "github_app_private_key_secret_arn", "github_repo_slug",
        "hosted_zone_id", "kms_key_alias", "origin_host", "render_only",
        "stack_instance_name", "vps_instance_type", "vps_root_volume_gb",
        "vps_ssh_key_name",
    }),
}


class PulumiStackConfigError(ValueError):
    """A requested stack cannot be safely materialized."""


def build_pulumi_stack_config(
    conn: Any, project: str, stack_name: str
) -> dict[str, Any]:
    """Return schema-v2 inputs for one exact declared stack."""
    selected_stack = str(stack_name or "").strip()
    if not selected_stack:
        raise PulumiStackConfigError("stack name is required")
    ident = resolve_project(conn, project, required=False)
    if ident is None:
        raise LookupError(f"project {project!r} was not found")
    settings = _load_project_renderer_settings(conn, ident.slug)
    project_root = Path(".")
    values = gather_pulumi_values(
        ident.slug,
        project_root,
        settings,
        pulumi_stack=selected_stack,
    )
    stack_types = gather_pulumi_stacks(ident.slug, project_root, settings)
    instances = gather_pulumi_stack_instances(ident.slug, project_root, settings)
    selected_types, selected_instances = select_pulumi_targets(
        selected_stack,
        stack_types,
        instances,
        settings=settings,
        values=values,
    )
    if selected_instances:
        stack_kind = "environment"
        render_values = instance_template_values(selected_instances[0], values)
    else:
        stack_kind = selected_types[0]
        render_values = _legacy_render_values(
            stack_kind, values, settings, stack_types
        )
    render_values = _selected_render_values(stack_kind, render_values)
    operator_state = _selected_operator_state(settings, selected_stack)
    return {
        "config_schema": STACK_CONFIG_SCHEMA,
        "project_id": ident.id,
        "project_slug": ident.slug,
        "stack_name": selected_stack,
        "stack_kind": stack_kind,
        "render_values": render_values,
        "operator_state": operator_state,
        "authority": _authority(
            conn, ident.slug, settings, stack_kind, render_values
        ),
    }


def _legacy_render_values(
    stack_kind: str,
    values: Mapping[str, str],
    settings: Any,
    declared_stack_types: list[str],
) -> dict[str, str]:
    result = dict(values)
    context = _pulumi_context_from_settings(settings)
    result.setdefault("domain_txt_records_json", _domain_txt_records_json(context))
    result.setdefault("domain_mx_records_json", _domain_mx_records_json(context))
    if stack_kind == "domain":
        result["import_zone_id"] = str(context.get("importZoneId", "") or "")
        result["manage_registration"] = (
            "true" if context.get("manageRegistration") else "false"
        )
    elif stack_kind == "registry":
        result["repository_name"] = (
            str(context.get("containerRepositoryName", "") or "")
            or f"{settings.deploy_namespace}-core"
        )
    elif stack_kind == "infra" and "domain" in declared_stack_types:
        result["domain_txt_records_json"] = "[]"
        result["domain_mx_records_json"] = "[]"
    return result


def _selected_operator_state(settings: Any, stack_name: str) -> dict[str, str]:
    capability_state = settings.capabilities.get(
        PULUMI_STATE_CAPABILITY_TYPE, {}
    ).get("stack_state")
    if capability_state is not None:
        validated = validate_stack_state(capability_state)
        if stack_name in validated:
            return validated[stack_name]
    for environment in settings.environments:
        pulumi = _first_mapping(environment.settings.get("pulumi"))
        if str(pulumi.get("stack_name") or "") != stack_name:
            continue
        raw = {
            "secrets_provider": pulumi.get("secrets_provider"),
            "encrypted_key": pulumi.get("encrypted_key"),
        }
        return validate_stack_state({stack_name: raw})[stack_name]
    raise PulumiStackConfigError(
        f"Pulumi operator state is missing for stack {stack_name!r}"
    )


def _selected_render_values(
    stack_kind: str, values: Mapping[str, str]
) -> dict[str, str]:
    if stack_kind == "runner-fleet":
        keys = frozenset(
            key for key in values
            if key.startswith("runner_fleet_")
        ) | {"deploy_namespace", "project_name"}
    else:
        keys = _RENDER_KEYS_BY_KIND.get(stack_kind)
    if keys is None:
        raise PulumiStackConfigError(
            f"Pulumi stack kind {stack_kind!r} is not supported"
        )
    return {key: values[key] for key in sorted(keys) if key in values}


def _authority(
    conn: Any,
    project: str,
    settings: Any,
    stack_kind: str,
    render_values: Mapping[str, str],
) -> dict[str, Any]:
    aws_capability = "aws-admin"
    aws_settings = settings.capabilities.get(aws_capability, {})
    region = str(aws_settings.get("region") or "").strip()
    state_settings = settings.capabilities.get(PULUMI_STATE_CAPABILITY_TYPE, {})
    state_bucket = str(state_settings.get("state_bucket") or "").strip()
    if not region or not state_bucket:
        raise PulumiStackConfigError(
            "Pulumi AWS region and state bucket authority are required"
        )
    repo_key = (
        "runner_fleet_repo"
        if stack_kind == "runner-fleet"
        else "github_repo_slug"
    )
    api_key = (
        "runner_fleet_github_api_url"
        if stack_kind == "runner-fleet"
        else "github_api_url"
    )
    desired_repo = str(render_values.get(repo_key) or "").strip()
    desired_api = str(render_values.get(api_key) or "").strip()
    github_project, binding = _github_binding_for_repo(
        conn, desired_repo, desired_api
    )
    if stack_kind == "runner-fleet":
        permissions = _RUNNER_FLEET_GITHUB_INTENT
    elif stack_kind in {"environment", "registry"}:
        permissions = _GITHUB_VARIABLES_INTENT
    else:
        permissions = _GITHUB_METADATA_INTENT
    return {
        "aws_capability": aws_capability,
        "aws_region": region,
        "backend_url": f"s3://{state_bucket}?region={region}",
        "github_project": github_project or project,
        "github_repo": str(binding.get("github_repo") or ""),
        "github_api_url": str(binding.get("api_url") or ""),
        "github_permissions": dict(permissions),
        "sensitive_paths": [
            "operator_state.secrets_provider",
            "operator_state.encrypted_key",
        ],
    }


def _github_binding_for_repo(
    conn: Any, desired_repo: str, desired_api: str
) -> tuple[str, Mapping[str, Any]]:
    normalized = normalize_github_repo(desired_repo)
    if not normalized:
        return "", {}
    rows = conn.execute(
        "SELECT p.slug, b.github_repo, b.api_url "
        "FROM project_github_repo_bindings b "
        "JOIN projects p ON p.id=b.project_id"
    ).fetchall()
    for row in rows:
        repo = str(row[1] or "")
        api_url = str(row[2] or "")
        if normalize_github_repo(repo) != normalized:
            continue
        if desired_api and api_url.rstrip("/") != desired_api.rstrip("/"):
            continue
        return str(row[0]), {"github_repo": repo, "api_url": api_url}
    raise PulumiStackConfigError(
        f"rendered GitHub repository {desired_repo!r} has no project binding"
    )


__all__ = [
    "PulumiStackConfigError",
    "STACK_CONFIG_SCHEMA",
    "build_pulumi_stack_config",
]
