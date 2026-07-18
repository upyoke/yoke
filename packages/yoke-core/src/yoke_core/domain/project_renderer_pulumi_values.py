"""Pulumi-specific renderer value projection."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from . import json_helper
from .project_renderer_pulumi_ci import delivery_ci_values
from .project_renderer_pulumi_context import _pulumi_context_from_settings
from .project_renderer_pulumi_runner_fleet import (
    runner_fleet_stack_name,
    runner_fleet_values,
)
from .project_renderer_settings import (
    PULUMI_STATE_CAPABILITY_TYPE,
    ProjectRendererSettings,
    _stringify,
    load_project_renderer_settings,
)
from .pulumi_state_capability import COMPONENT_TYPE_ALIASES_KEY
from .project_renderer_values import _values_from_settings


def gather_pulumi_values(
    project: str,
    project_root: Path,
    settings: ProjectRendererSettings | None = None,
    *,
    pulumi_stack: str | None = None,
) -> Dict[str, str]:
    """Return the Pulumi value dict: inherited keys + VPS + Pulumi + CI keys."""
    del project_root
    if settings is None:
        settings = load_project_renderer_settings(project)
    values = dict(_values_from_settings(project, settings))
    data = _pulumi_context_from_settings(settings)

    values["vps_instance_type"] = _stringify(data.get("vpsInstanceType"))
    values["vps_root_volume_gb"] = _stringify(data.get("vpsRootVolumeGb"))
    values["vps_ssh_key_name"] = _stringify(data.get("vpsSshKeyName"))
    values["vps_iam_instance_profile_name"] = _stringify(
        data.get("vpsIamInstanceProfileName")
    )
    values["origin_id"] = _stringify(data.get("originId"))
    values["distribution_bucket_name"] = _stringify(
        data.get("distributionBucketName")
    )
    values["domain_txt_records_json"] = _domain_txt_records_json(data)
    values["domain_mx_records_json"] = _domain_mx_records_json(data)
    state = settings.capabilities.get(PULUMI_STATE_CAPABILITY_TYPE, {})
    values["component_type_aliases_json"] = json_helper.dumps_compact(
        state.get(COMPONENT_TYPE_ALIASES_KEY, {})
    )

    namespace = settings.deploy_namespace
    values["kms_key_alias"] = _stringify(
        data.get("kmsKeyAlias"), f"alias/{namespace}-pulumi-state"
    )
    values["state_bucket"] = _stringify(
        data.get("stateBucket"), f"{namespace}-pulumi-state"
    )
    values["pulumi_infra_stack_name"] = _stringify(
        data.get("pulumiInfraStackName"), f"{namespace}-infra"
    )
    values["pulumi_vps_stack_name"] = _stringify(
        data.get("pulumiVpsStackName"), f"{namespace}-vps"
    )
    values["pulumi_runner_fleet_stack_name"] = runner_fleet_stack_name(settings)

    github = settings.capabilities.get("github", {})
    owner = _stringify(github.get("repo_owner"))
    repo = _stringify(github.get("repo_name"))
    values["github_repo_slug"] = f"{owner}/{repo}" if owner and repo else ""
    manage_default = github.get("ci_oidc_manage_provider")
    values["manage_github_oidc_provider"] = _stringify(
        manage_default if manage_default is not None else True
    )
    values.update(delivery_ci_values(settings))
    runner_fleet_enabled = "runner-fleet" in (data.get("stacks") or [])
    if (
        pulumi_stack is None
        or pulumi_stack == values["pulumi_runner_fleet_stack_name"]
    ):
        values.update(runner_fleet_values(
            settings,
            fallback_repo=values["github_repo_slug"],
            enabled=runner_fleet_enabled,
        ))
    return values


def _domain_txt_records_json(context: Dict[str, object]) -> str:
    records = context.get("domainTxtRecords")
    if not isinstance(records, list):
        records = []
    return json_helper.dumps_compact(records).replace("'", "''")


def _domain_mx_records_json(context: Dict[str, object]) -> str:
    records = context.get("domainMxRecords")
    if not isinstance(records, list):
        records = []
    return json_helper.dumps_compact(records).replace("'", "''")


__all__ = ["gather_pulumi_values"]
