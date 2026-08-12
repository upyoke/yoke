"""Machine-profile validation and token refresh for local GitHub operations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import urllib.error

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_git_credential_file
from yoke_cli.config import github_user_tokens
from yoke_cli.config import machine_config
from yoke_cli.config import github_machine_operation
from yoke_contracts.github_auth_transience import (
    GITHUB_AUTH_RETRY_RECIPE,
    TransientGitHubAuthError,
    auth_failure_chain,
)


class GitHubLocalUserAccessError(RuntimeError):
    """The saved machine App profile cannot provide local GitHub access."""


class TransientGitHubLocalUserAccessError(
    GitHubLocalUserAccessError, TransientGitHubAuthError
):
    """A local access read failed transiently; the authorization still stands."""


# A single unauthorized refresh response is retry-shaped: a sibling process may
# have rotated the refresh token between this reader's document read and its
# exchange. A genuinely revoked authorization answers with an OAuth error
# payload instead, which stays permanent.
_TRANSIENT_HTTP_STATUS = frozenset({401, 408, 429})


def access_token(
    config_path: str | Path | None = None,
    *,
    opener: Callable[..., Any] | None = None,
    profile_opener: Callable[..., Any] | None = None,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
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
                local_connection_selected=local_connection_selected,
                opener=profile_opener,
            )
            return github_user_tokens.access_token_from_machine_config(
                config_path=config_path,
                opener=opener,
                profile_opener=profile_opener,
                _profile_proven=True,
                _expected_service_api_url=service_api_url,
                _expected_local_connection=local_connection_selected,
                now=now,
            )
    except (
        github_app_public_profile.GitHubAppPublicProfileError,
        github_user_tokens.GitHubUserTokenError,
        github_machine_operation.GitHubMachineOperationError,
        machine_config.MachineConfigError,
    ) as exc:
        if is_transient_access_failure(exc):
            raise TransientGitHubLocalUserAccessError(
                f"{exc}; {GITHUB_AUTH_RETRY_RECIPE}"
            ) from exc
        raise GitHubLocalUserAccessError(str(exc)) from exc


def is_transient_access_failure(error: BaseException) -> bool:
    """Report whether an access failure describes contention rather than absence."""

    for cause in auth_failure_chain(error):
        if isinstance(
            cause,
            (
                TransientGitHubAuthError,
                github_git_credential_file.CredentialFileBusy,
            ),
        ):
            return True
        if isinstance(cause, urllib.error.HTTPError):
            return cause.code in _TRANSIENT_HTTP_STATUS or cause.code >= 500
        if isinstance(cause, (urllib.error.URLError, TimeoutError, ConnectionError)):
            return True
    return False


__all__ = [
    "GitHubLocalUserAccessError",
    "TransientGitHubLocalUserAccessError",
    "access_token",
    "is_transient_access_failure",
]
