"""Project artifact source, checkout identity, and policy validation."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_cli.project_artifacts.errors import ProjectArtifactError
from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    normalize_github_repository,
    validate_github_web_endpoint,
)
from yoke_contracts.project_artifacts import (
    PROJECT_ARTIFACT_GENERATED_REFERENCE_PREFIX,
    PROJECT_ARTIFACT_PACKAGED_SOURCE,
    PROJECT_ARTIFACT_SOURCE_DEV_SOURCE,
)


def validate_template_source(source: str, *, source_dev_admin: bool) -> None:
    allowed_sources = {PROJECT_ARTIFACT_PACKAGED_SOURCE}
    if source_dev_admin:
        allowed_sources.add(PROJECT_ARTIFACT_SOURCE_DEV_SOURCE)
    if source not in allowed_sources:
        if source_dev_admin:
            raise ProjectArtifactError(
                f"artifact bundle returned an unknown template source: {source!r}"
            )
        raise ProjectArtifactError(
            "product artifact refresh requires the packaged template mirror; "
            f"server returned {source!r}"
        )


def validate_checkout_identity(
    value: Any,
    project_id: int,
    project_slug: str,
) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "project_id",
        "project_slug",
        "github_repo",
        "github_web_url",
    }:
        raise ProjectArtifactError("artifact bundle checkout_identity is invalid")
    if value.get("project_id") != project_id:
        raise ProjectArtifactError(
            "artifact bundle checkout_identity project id does not match"
        )
    identity_slug = value.get("project_slug")
    if not isinstance(identity_slug, str) or identity_slug != project_slug:
        raise ProjectArtifactError(
            "artifact bundle checkout_identity project slug does not match"
        )
    repo = value.get("github_repo")
    web_url = value.get("github_web_url")
    if repo is None and web_url is None:
        return
    if not isinstance(repo, str) or not isinstance(web_url, str):
        raise ProjectArtifactError("artifact bundle checkout_identity is invalid")
    try:
        canonical_web = validate_github_web_endpoint(web_url).base_url
        canonical_repo = normalize_github_repository(repo, web_url=canonical_web)
    except GitHubApiOriginError as exc:
        raise ProjectArtifactError(
            f"artifact bundle checkout_identity is invalid: {exc}"
        ) from exc
    if canonical_web != web_url or canonical_repo != repo:
        raise ProjectArtifactError(
            "artifact bundle checkout_identity must use canonical values"
        )


def validate_artifact_policy(value: Any) -> None:
    expected = {
        "generated_reference_prefix": PROJECT_ARTIFACT_GENERATED_REFERENCE_PREFIX,
        "project_owned_prefixes": [".yoke/runbooks/"],
        "deviation_policy": "preserve-and-refuse",
        "prune_policy": "manifest-owned-only",
    }
    if value != expected:
        raise ProjectArtifactError(
            "artifact bundle policy does not match this CLI's safety contract"
        )


__all__ = [
    "validate_artifact_policy",
    "validate_checkout_identity",
    "validate_template_source",
]
