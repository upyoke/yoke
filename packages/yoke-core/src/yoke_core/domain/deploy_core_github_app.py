"""GitHub App key preflight and convergence for core deployment."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import github_app_deployment
from yoke_core.domain.deploy_remote import aws_capability_env

github_app_env_lines = github_app_deployment.github_app_env_lines
github_app_render_values = github_app_deployment.github_app_render_values


def preflight(
    runner: Any,
    env: Any,
) -> tuple[Mapping[str, str], str | None]:
    """Resolve AWS authority, then verify the App key without host writes."""
    aws_env = aws_capability_env(env.project, env.aws_region)
    private_key = github_app_deployment.preflight_github_app_private_key(
        runner,
        env,
        aws_env,
    )
    return aws_env, private_key


def converge(runner: Any, env: Any, private_key: str | None) -> None:
    """Deliver or remove the App key after read-only preflight succeeds."""
    github_app_deployment.converge_github_app_private_key(
        runner,
        env,
        private_key_pem=private_key,
    )


__all__ = [
    "converge",
    "github_app_env_lines",
    "github_app_render_values",
    "preflight",
]
