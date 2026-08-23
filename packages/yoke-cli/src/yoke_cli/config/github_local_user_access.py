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
from yoke_contracts.github_rate_limit import is_rate_limit_body


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
    """Validate the saved public profile, then refresh locally against GitHub.

    A caller naming no connection gets the selected one resolved here, once,
    and carried through both the profile proof and the credential store, so
    every reader proves the binding the merge child and ``yoke github status``
    pin explicitly — a reader under an owner-only admin connection included,
    which proves against the https plane that connection administers.
    """
    try:
        with github_machine_operation.operation_lock(config_path):
            github = machine_config.github_config(config_path)
            if not github:
                raise GitHubLocalUserAccessError(
                    "machine GitHub App authorization is not configured"
                )
            if service_api_url is None and not local_connection_selected:
                service_api_url = (
                    github_app_public_profile.selected_https_service_api_url(
                        config_path
                    )
                )
                local_connection_selected = service_api_url is None
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
                _transient_access_message(exc)
            ) from exc
        raise GitHubLocalUserAccessError(str(exc)) from exc


def _http_error_body(error: urllib.error.HTTPError) -> str:
    cached = getattr(error, "_yoke_rate_limit_body", None)
    if isinstance(cached, str):
        return cached
    try:
        raw = error.read()
    except Exception:
        raw = b""
    text = (
        raw.decode("utf-8", errors="replace")
        if isinstance(raw, bytes)
        else str(raw or "")
    )
    try:
        setattr(error, "_yoke_rate_limit_body", text)
    except Exception:
        pass
    return text


def _is_rate_limit_http_error(error: urllib.error.HTTPError) -> bool:
    if error.code != 403:
        return False
    headers = error.headers or {}
    remaining = str(headers.get("X-RateLimit-Remaining") or "")
    body = _http_error_body(error)
    reason = str(getattr(error, "reason", "") or "")
    return (
        remaining == "0"
        or is_rate_limit_body(body)
        or is_rate_limit_body(reason)
    )


def _rate_limit_reset_text(error: urllib.error.HTTPError) -> str:
    headers = error.headers or {}
    return str(
        headers.get("X-RateLimit-Reset") or headers.get("Retry-After") or ""
    )


def _transient_access_message(error: BaseException) -> str:
    for cause in auth_failure_chain(error):
        if isinstance(cause, urllib.error.HTTPError) and _is_rate_limit_http_error(
            cause
        ):
            reset = _rate_limit_reset_text(cause)
            reset_note = f"; reset at {reset}" if reset else ""
            return (
                f"GitHub rate-limited (HTTP {cause.code}){reset_note}; "
                f"{GITHUB_AUTH_RETRY_RECIPE}"
            )
    return f"{error}; {GITHUB_AUTH_RETRY_RECIPE}"


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
            if cause.code in _TRANSIENT_HTTP_STATUS or cause.code >= 500:
                return True
            if _is_rate_limit_http_error(cause):
                return True
            return False
        if isinstance(cause, (urllib.error.URLError, TimeoutError, ConnectionError)):
            return True
    return False


__all__ = [
    "GitHubLocalUserAccessError",
    "TransientGitHubLocalUserAccessError",
    "access_token",
    "is_transient_access_failure",
]
