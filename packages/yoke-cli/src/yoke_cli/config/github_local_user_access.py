"""Machine-profile validation and token refresh for local GitHub operations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_user_tokens
from yoke_cli.config import machine_config
from yoke_cli.config import github_machine_operation


class GitHubLocalUserAccessError(RuntimeError):
    """The saved machine App profile cannot provide local GitHub access."""


def access_token(
    config_path: str | Path | None = None,
    *,
    opener: Callable[..., Any] | None = None,
    profile_opener: Callable[..., Any] | None = None,
    service_api_url: str | None = None,
    now: datetime | None = None,
) -> github_user_tokens.LocalUserAccessToken:
    """Validate the saved public profile, then refresh locally against GitHub."""
    try:
        with github_machine_operation.operation_lock(config_path):
            github = machine_config.github_config(config_path)
            if not github:
                raise GitHubLocalUserAccessError(
                    "machine GitHub App authorization is not configured"
                )
            github_app_public_profile.resolve_selected_and_match(
                github,
                config_path=config_path,
                service_api_url=service_api_url,
                opener=profile_opener,
            )
            return github_user_tokens.access_token_from_machine_config(
                config_path=config_path,
                opener=opener,
                profile_opener=profile_opener,
                _profile_proven=True,
                _expected_service_api_url=service_api_url,
                now=now,
            )
    except (
        github_app_public_profile.GitHubAppPublicProfileError,
        github_user_tokens.GitHubUserTokenError,
        github_machine_operation.GitHubMachineOperationError,
        machine_config.MachineConfigError,
    ) as exc:
        raise GitHubLocalUserAccessError(str(exc)) from exc


__all__ = ["GitHubLocalUserAccessError", "access_token"]
