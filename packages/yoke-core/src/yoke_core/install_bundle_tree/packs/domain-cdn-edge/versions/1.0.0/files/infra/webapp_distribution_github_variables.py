"""Repository release variables owned by an environment stack."""

from __future__ import annotations

import re

import pulumi
import pulumi_github as github

from webapp_github_repository_provider import create_repository_provider


def _variable_prefix(variable_namespace: str, environment: str) -> str:
    parts = (variable_namespace, environment, "distribution")
    normalized = [re.sub(r"[^A-Za-z0-9]+", "_", part).strip("_").upper() for part in parts]
    if any(not part for part in normalized):
        raise pulumi.RunError(
            "distribution repository variables require non-empty namespace and environment"
        )
    return "_".join(normalized)


def create_distribution_variables(
    *,
    variable_namespace: str,
    environment: str,
    github_repo: str,
    github_api_url: str,
    base_url: pulumi.Input[str],
    bucket: pulumi.Input[str],
    cloudfront_id: pulumi.Input[str],
    origin_id: pulumi.Input[str],
    child_opts: pulumi.ResourceOptions,
) -> tuple[github.ActionsVariable, ...]:
    """Converge the complete non-secret distribution publishing contract."""
    owner, separator, repository = github_repo.partition("/")
    if not separator or not owner.strip() or not repository.strip() or "/" in repository:
        raise pulumi.RunError("github_repo must use the exact owner/repository form")
    provider = create_repository_provider(
        "githubDistributionVariableProvider",
        owner=owner,
        api_url=github_api_url,
        required_permissions=("actions_variables: read for preview or write for apply",),
        authority_name="environment stack",
        opts=child_opts,
    )
    provider_opts = pulumi.ResourceOptions.merge(
        child_opts,
        pulumi.ResourceOptions(provider=provider),
    )
    prefix = _variable_prefix(variable_namespace, environment)
    definitions = (
        ("BaseUrl", f"{prefix}_BASE_URL", base_url),
        ("Bucket", f"{prefix}_BUCKET", bucket),
        ("CloudfrontId", f"{prefix}_CLOUDFRONT_ID", cloudfront_id),
        ("OriginId", f"{prefix}_ORIGIN_ID", origin_id),
    )
    return tuple(
        github.ActionsVariable(
            f"githubDistribution{resource_suffix}Variable",
            repository=repository,
            variable_name=variable_name,
            value=value,
            opts=provider_opts,
        )
        for resource_suffix, variable_name, value in definitions
    )


__all__ = ["create_distribution_variables"]
