"""GitHub App key preflight and convergence for core deployment."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import github_app_deployment
from yoke_core.domain.deploy_remote import aws_capability_env
from yoke_core.domain.github_app_origin_key import (
    converge_from_instance_role,
    verify_and_promote_in_core_image,
)

github_app_env_lines = github_app_deployment.github_app_env_lines
github_app_render_values = github_app_deployment.github_app_render_values


def preflight(
    runner: Any,
    env: Any,
) -> Mapping[str, str]:
    """Resolve deploy AWS authority without reading App private-key material."""
    del runner
    return aws_capability_env(env.project, env.aws_region)


def converge(runner: Any, env: Any) -> None:
    """Let the origin instance role retrieve or remove its own App key."""
    converge_from_instance_role(runner, env)


def verify(runner: Any, env: Any, image_ref: str) -> None:
    """Verify the fetched key inside the newly pulled core image."""
    verify_and_promote_in_core_image(runner, env, image_ref)


__all__ = [
    "converge",
    "github_app_env_lines",
    "github_app_render_values",
    "preflight",
    "verify",
]
