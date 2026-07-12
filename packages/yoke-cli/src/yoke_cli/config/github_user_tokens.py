"""Refresh-only access over a serialized refresh-token rotation chain."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_cli.config import github_git_credential_store as credential_store


class GitHubUserTokenError(RuntimeError):
    """A local GitHub App user token could not be obtained."""


class GitHubUserTokenResponseError(GitHubUserTokenError):
    """GitHub refused a user-token refresh request."""


@dataclass(frozen=True)
class LocalUserAccessToken:
    access_token: str = field(repr=False)
    expires_at: datetime
    refresh_token: str = field(repr=False)
    refresh_expires_at: datetime
    scope: str = ""
    token_type: str = "bearer"
    refresh_rotated: bool = False
    refresh_credential_ref: str = ""
    cached: bool = False

def access_token_from_machine_config(
    *,
    config_path: str | Path | None = None,
    client_secret: str | None = None,
    opener: Callable[..., Any] | None = None,
    now: datetime | None = None,
    timeout_seconds: float = 30.0,
    profile_opener: Callable[..., Any] | None = None,
    _profile_proven: bool = False,
    _expected_service_api_url: str | None = None,
    _expected_local_connection: bool = False,
) -> LocalUserAccessToken:
    """Refresh under lock and return a transient, never-persisted access token."""
    try:
        payload = credential_store.access_token_from_machine_config(
            _resolved_config_path(config_path),
            client_secret=client_secret,
            opener=opener,
            now=now,
            timeout_seconds=timeout_seconds,
            profile_opener=profile_opener,
            profile_proven=_profile_proven,
            expected_service_api_url=_expected_service_api_url,
            expected_local_connection=_expected_local_connection,
        )
    except credential_store.GitHubCredentialStoreError as exc:
        raise GitHubUserTokenError(str(exc)) from exc
    return _local_token(payload)


def refresh_user_access_token(
    *,
    client_id: str,
    refresh_token: str,
    client_secret: str | None = None,
    login_base: str = credential_store.DEFAULT_GITHUB_WEB_URL,
    opener: Callable[..., Any] | None = None,
    now: datetime | None = None,
    timeout_seconds: float = 30.0,
) -> LocalUserAccessToken:
    """Exchange a refresh token without reading or mutating machine config."""
    try:
        payload = credential_store.refresh_credential_document(
            client_id=client_id,
            refresh_token=refresh_token,
            client_secret=client_secret,
            login_base=login_base,
            opener=opener,
            now=now,
            timeout_seconds=timeout_seconds,
        )
    except credential_store.GitHubCredentialStoreError as exc:
        raise GitHubUserTokenResponseError(str(exc)) from exc
    return _local_token(payload)


def store_initial_token(
    path: str | Path,
    token_response: Mapping[str, Any],
    *,
    now: datetime | None = None,
    device_flow_completed: bool = False,
    config_path: str | Path | None = None,
) -> Path:
    """Persist the first device-flow token as one owner-only document."""
    if device_flow_completed is not True:
        raise GitHubUserTokenError(
            "initial GitHub App credentials may be stored only after device flow"
        )
    try:
        document = credential_store.credential_document_from_token_response(
            token_response, now=now, config_path=config_path,
        )
        return credential_store.write_credential_document(path, document)
    except credential_store.GitHubCredentialStoreError as exc:
        raise GitHubUserTokenError(str(exc)) from exc


def _local_token(payload: Mapping[str, Any]) -> LocalUserAccessToken:
    return LocalUserAccessToken(
        access_token=str(payload["access_token"]),
        expires_at=datetime.fromisoformat(str(payload["expires_at"])),
        refresh_token=str(payload["refresh_token"]),
        refresh_expires_at=datetime.fromisoformat(
            str(payload["refresh_expires_at"])
        ),
        scope=str(payload.get("scope") or ""),
        token_type=str(payload.get("token_type") or "bearer"),
        refresh_rotated=bool(payload.get("refresh_rotated")),
        refresh_credential_ref=str(payload.get("refresh_credential_ref") or ""),
        cached=bool(payload.get("cached")),
    )


def _resolved_config_path(path: str | Path | None) -> Path:
    from yoke_cli.config import machine_config

    return machine_config.config_path(path)


__all__ = [
    "GitHubUserTokenError",
    "GitHubUserTokenResponseError",
    "LocalUserAccessToken",
    "access_token_from_machine_config",
    "refresh_user_access_token",
    "store_initial_token",
]
