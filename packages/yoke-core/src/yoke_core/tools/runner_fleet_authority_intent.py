"""Canonical runner-stack intent bound to one validated settings snapshot."""

from __future__ import annotations

import hashlib
from typing import Mapping

from yoke_core.domain import json_helper
from yoke_core.domain.project_renderer_pulumi_runner_fleet import (
    runner_fleet_stack_name,
)
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings


def authority_intent_envelope(
    settings: ProjectRendererSettings,
    values: Mapping[str, str],
    *,
    aws_capability: str,
    aws_region: str,
) -> str:
    """Serialize every snapshot-derived mutable runner-stack input."""
    labels = json_helper.loads_text(values["runner_fleet_labels_json"])
    if not isinstance(labels, list) or any(
        not isinstance(label, str) for label in labels
    ):
        raise ValueError("runner-fleet labels must be a JSON string array")
    routing_text = values["runner_fleet_routing_enabled"]
    if routing_text not in {"false", "true"}:
        raise ValueError("runner-fleet routing intent must be true or false")
    authority = {
        "project": settings.project,
        "deploy_namespace": settings.deploy_namespace,
        "stack_name": runner_fleet_stack_name(settings),
        "aws_capability": aws_capability,
        "aws_region": aws_region,
        "github_capability": values["runner_fleet_github_capability"],
        "github_app_environment": values["runner_fleet_github_app_environment"],
        "repo": values["runner_fleet_repo"],
        "repo_owner": values["runner_fleet_github_repo_owner"],
        "repo_name": values["runner_fleet_github_repo_name"],
        "installation_id": values["runner_fleet_github_installation_id"],
        "repository_id": values["runner_fleet_github_repository_id"],
        "app_issuer": values["runner_fleet_github_app_issuer"],
        "api_url": values["runner_fleet_github_api_url"],
        "web_url": values["runner_fleet_github_web_url"],
        "private_key_secret_arn": values["runner_fleet_github_private_key_secret_arn"],
        "runner_labels": labels,
        "runner_variable_name": values["runner_fleet_variable_name"],
        "routing_enabled": routing_text == "true",
        "runner_count": int(values["runner_fleet_runner_count"]),
        "max_runner_count": int(values["runner_fleet_max_runner_count"]),
        "instance_type": values["runner_fleet_instance_type"],
        "architecture": values["runner_fleet_architecture"],
        "root_volume_gb": int(values["runner_fleet_root_volume_gb"]),
        "idle_shutdown_minutes": int(values["runner_fleet_idle_shutdown_minutes"]),
        "shutdown_mode": values["runner_fleet_shutdown_mode"],
    }
    canonical = json_helper.dumps_compact(dict(sorted(authority.items())))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return json_helper.dumps_compact(
        {
            "schema": 1,
            "authority": authority,
            "sha256": digest,
        }
    )


__all__ = ["authority_intent_envelope"]
