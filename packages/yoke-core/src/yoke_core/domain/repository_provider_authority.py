"""Hosted, repository-scoped provider authority for Pulumi previews."""

from __future__ import annotations

import hashlib

from yoke_contracts.github_origin import normalize_github_repository

from yoke_core.domain import json_helper
from yoke_core.domain.project_renderer_pulumi_runner_fleet import (
    runner_fleet_values,
)
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings


def repository_provider_intent_from_settings(
    settings: ProjectRendererSettings,
    *,
    expected_repo: str,
) -> str:
    """Build the broker intent for one repo already bound into a stack."""

    values = runner_fleet_values(settings, fallback_repo="", enabled=True)
    bound_repo = normalize_github_repository(values["runner_fleet_repo"])
    selected_repo = normalize_github_repository(expected_repo)
    if bound_repo != selected_repo:
        raise ValueError(
            "hosted repository provider authority does not match the "
            f"requested repository ({bound_repo} != {selected_repo})"
        )
    authority = {
        "project": settings.project,
        "deploy_namespace": settings.deploy_namespace,
        "aws_capability": values["runner_fleet_aws_capability"],
        "aws_region": values["runner_fleet_aws_region"],
        "repo": bound_repo,
        "repo_owner": values["runner_fleet_github_repo_owner"],
        "repo_name": values["runner_fleet_github_repo_name"],
        "installation_id": values["runner_fleet_github_installation_id"],
        "repository_id": values["runner_fleet_github_repository_id"],
        "app_issuer": values["runner_fleet_github_app_issuer"],
        "api_url": values["runner_fleet_github_api_url"],
        "private_key_secret_arn": (
            values["runner_fleet_github_private_key_secret_arn"]
        ),
        "token_broker_function": values[
            "runner_fleet_token_broker_function"
        ],
    }
    canonical = json_helper.dumps_compact(dict(sorted(authority.items())))
    return json_helper.dumps_compact({
        "schema": 1,
        "authority": authority,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    })


__all__ = ["repository_provider_intent_from_settings"]
