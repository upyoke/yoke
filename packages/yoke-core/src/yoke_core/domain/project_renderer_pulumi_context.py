"""Legacy Pulumi context projection for the project renderer.

Projects the DB-backed renderer settings into the camelCase context
field names the Pulumi value/stack gatherers consume.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from .project_renderer_settings import (
    PULUMI_STATE_CAPABILITY_TYPE,
    ProjectRendererSettings,
    load_project_renderer_settings,
    primary_domain,
    primary_server,
)


def _read_pulumi_context(
    project: str,
    project_root: Path,
    settings: ProjectRendererSettings | None = None,
) -> Dict[str, object]:
    """Return DB-backed Pulumi settings in the legacy context shape."""
    del project_root
    if settings is None:
        settings = load_project_renderer_settings(project)
    return _pulumi_context_from_settings(settings)


def _pulumi_context_from_settings(settings) -> Dict[str, object]:
    """Project DB settings into the legacy Pulumi context field names."""
    domain = primary_domain(settings)
    server = primary_server(settings)
    site_pulumi = settings.site_settings.get("pulumi", {})
    site_cdn = settings.site_settings.get("cdn", {})
    state = settings.capabilities.get(PULUMI_STATE_CAPABILITY_TYPE, {})

    data: Dict[str, object] = {}
    if isinstance(site_pulumi, dict):
        data.update(site_pulumi)
    if isinstance(state, dict) and "stacks" in state:
        data["stacks"] = state["stacks"]
    if isinstance(site_cdn, dict):
        data["originId"] = site_cdn.get("origin_id", "")
        data["distributionBucketName"] = site_cdn.get(
            "distribution_bucket_name", ""
        )
    data["importZoneId"] = domain.get("hosted_zone_id", "")
    data["manageRegistration"] = bool(domain.get("manage_registration"))
    data["domainTxtRecords"] = domain.get("txt_records", [])
    data["domainMxRecords"] = domain.get("mx_records", [])
    data["vpsInstanceType"] = server.get("instance_type", "")
    data["vpsRootVolumeGb"] = server.get("root_volume_gb", "")
    data["vpsSshKeyName"] = server.get("aws_key_pair_name", "")
    data["vpsIamInstanceProfileName"] = server.get(
        "iam_instance_profile_name", ""
    )
    data["kmsKeyAlias"] = state.get("kms_key_alias", "")
    data["stateBucket"] = state.get("state_bucket", "")
    return data


__all__ = ["_pulumi_context_from_settings", "_read_pulumi_context"]
