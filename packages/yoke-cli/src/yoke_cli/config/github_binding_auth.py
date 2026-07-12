"""Profile-bound user access for GitHub project operations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_user_tokens
from yoke_cli.config import machine_config
from yoke_cli.config import github_machine_operation


class GitHubBindingAuthError(RuntimeError):
    """A project token cannot be used for the selected Yoke service."""


@dataclass(frozen=True)
class ProfileBoundUserAccess:
    """Transient token and canonical metadata proven against one service."""

    token: github_user_tokens.LocalUserAccessToken
    api_url: str
    web_url: str
    app_id: int
    app_slug: str


def access_token_for_binding(
    config_path: str | Path | None = None,
    *,
    profile_opener: Callable[..., Any] | None = None,
    token_opener: Callable[..., Any] | None = None,
) -> github_user_tokens.LocalUserAccessToken:
    """Verify the public App identity before refreshing a project token."""
    return profile_bound_access_for_binding(
        config_path,
        profile_opener=profile_opener,
        token_opener=token_opener,
    ).token


def profile_bound_access_for_binding(
    config_path: str | Path | None = None,
    *,
    profile_opener: Callable[..., Any] | None = None,
    token_opener: Callable[..., Any] | None = None,
) -> ProfileBoundUserAccess:
    """Read, prove, and return one internally consistent binding authority."""
    with locked_profile_bound_access_for_binding(
        config_path,
        profile_opener=profile_opener,
        token_opener=token_opener,
    ) as authority:
        return authority


@contextmanager
def locked_profile_bound_access_for_binding(
    config_path: str | Path | None = None,
    *,
    profile_opener: Callable[..., Any] | None = None,
    token_opener: Callable[..., Any] | None = None,
) -> Iterator[ProfileBoundUserAccess]:
    """Hold the machine authority lock through a caller's service dispatch."""

    lock = github_machine_operation.operation_lock(config_path)
    try:
        lock.__enter__()
    except github_machine_operation.GitHubMachineOperationError as exc:
        raise GitHubBindingAuthError(str(exc)) from exc
    try:
        try:
            github = machine_config.github_config(config_path)
            if not github:
                raise GitHubBindingAuthError(
                    "machine GitHub App authorization is not configured"
                )
            profile = github_app_public_profile.resolve_selected_and_match(
                github,
                config_path=config_path,
                opener=profile_opener,
            )
            token = github_user_tokens.access_token_from_machine_config(
                config_path=config_path,
                opener=token_opener,
                profile_opener=profile_opener,
                _profile_proven=True,
            )
            current = machine_config.github_config(config_path)
            if current != github:
                raise GitHubBindingAuthError(
                    "machine GitHub App profile changed while access was being "
                    "prepared; retry against the current connection"
                )
            authority = ProfileBoundUserAccess(
                token=token,
                api_url=profile.api_url,
                web_url=profile.web_url,
                app_id=profile.app_id,
                app_slug=profile.app_slug,
            )
        except (
            github_app_public_profile.GitHubAppPublicProfileError,
            github_user_tokens.GitHubUserTokenError,
            machine_config.MachineConfigError,
        ) as exc:
            raise GitHubBindingAuthError(str(exc)) from exc
        yield authority
    finally:
        lock.__exit__(None, None, None)


__all__ = [
    "GitHubBindingAuthError",
    "ProfileBoundUserAccess",
    "access_token_for_binding",
    "locked_profile_bound_access_for_binding",
    "profile_bound_access_for_binding",
]
