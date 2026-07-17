# AUTO-GENERATED template source: templates/webapp/infra/webapp_github_repository_provider.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Ephemeral GitHub provider authority for repository IaC."""

from __future__ import annotations

import hmac
import os
from collections.abc import Sequence

import pulumi
import pulumi_github as github


REPOSITORY_TOKEN_ENV = "RUNNER_FLEET_GITHUB_TOKEN"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"


def require_repository_token_environment(
    required_permissions: Sequence[str],
    *,
    authority_name: str = "repository IaC",
) -> None:
    """Require matched process-only token aliases with scoped guidance."""
    token = os.environ.get(REPOSITORY_TOKEN_ENV, "")
    provider_token = os.environ.get(GITHUB_TOKEN_ENV, "")
    if not token.strip():
        permission_text = ", ".join(required_permissions)
        raise pulumi.RunError(
            f"{authority_name} requires {REPOSITORY_TOKEN_ENV} with required "
            f"permissions: {permission_text}"
        )
    if not provider_token or not hmac.compare_digest(token, provider_token):
        raise pulumi.RunError(
            f"{authority_name} requires {GITHUB_TOKEN_ENV} to match "
            f"{REPOSITORY_TOKEN_ENV} for process-only provider auth"
        )


def create_repository_provider(
    resource_name: str,
    *,
    owner: str,
    api_url: str,
    required_permissions: Sequence[str],
    authority_name: str = "repository IaC",
    opts: pulumi.ResourceOptions,
) -> github.Provider:
    """Create a provider only from the wrapper's matched token aliases."""
    require_repository_token_environment(
        required_permissions,
        authority_name=authority_name,
    )
    if not owner.strip():
        raise pulumi.RunError("repository IaC requires a GitHub owner")
    provider_token = os.environ.pop(GITHUB_TOKEN_ENV)
    try:
        return github.Provider(
            resource_name,
            owner=owner,
            base_url=api_url.rstrip("/") + "/",
            opts=opts,
        )
    finally:
        os.environ[GITHUB_TOKEN_ENV] = provider_token


__all__ = [
    "GITHUB_TOKEN_ENV",
    "REPOSITORY_TOKEN_ENV",
    "create_repository_provider",
    "require_repository_token_environment",
]
