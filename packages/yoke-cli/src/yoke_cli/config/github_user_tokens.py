"""Local GitHub App user-access token refresh."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from yoke_cli.config import machine_config, secrets
from yoke_contracts import github_app_tokens as token_contract
from yoke_contracts.machine_config import schema as contract

urlopen = urllib.request.urlopen


class GitHubUserTokenError(RuntimeError):
    """A local GitHub App user-token refresh could not complete."""


class GitHubUserTokenResponseError(GitHubUserTokenError):
    """GitHub returned an error response during user-token refresh."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: str | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.error_code = error_code


@dataclass(frozen=True)
class LocalUserAccessToken:
    access_token: str
    expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    scope: str = ""
    token_type: str = "bearer"
    refresh_rotated: bool = False
    refresh_credential_ref: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "expires_at": self.expires_at.isoformat(),
            "refresh_expires_at": self.refresh_expires_at.isoformat(),
            "scope": self.scope,
            "token_type": self.token_type,
            "refresh_rotated": self.refresh_rotated,
            "refresh_credential_ref": self.refresh_credential_ref,
        }


def refresh_from_machine_config(
    *,
    config_path: str | Path | None = None,
    client_secret: str | None = None,
    login_base: str = token_contract.DEFAULT_GITHUB_WEB_BASE,
    opener: Callable[..., Any] | None = None,
    now: datetime | None = None,
    timeout_seconds: float = 30.0,
) -> LocalUserAccessToken:
    """Refresh the local GitHub App user token from machine config."""

    try:
        cfg = machine_config.github_config(config_path)
    except machine_config.MachineConfigError as exc:
        raise GitHubUserTokenError(str(exc)) from exc
    if not cfg:
        raise GitHubUserTokenError("machine GitHub App authorization is not configured")
    client_id = _required_string(cfg.get("client_id"), "github.client_id")
    authorization = cfg.get("authorization")
    if not isinstance(authorization, Mapping):
        raise GitHubUserTokenError("github.authorization must be an object")
    if authorization.get("kind") != contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION:
        raise GitHubUserTokenError(
            "github.authorization.kind must be github_app_user_authorization"
        )
    status = str(authorization.get("status") or "")
    if status != "authorized":
        raise GitHubUserTokenError(
            f"GitHub App user authorization is not authorized: {status or '<missing>'}"
        )
    refresh_ref = _required_string(
        authorization.get("refresh_credential_ref"),
        "github.authorization.refresh_credential_ref",
    )
    current_refresh_token = secrets.read_secret_file(
        refresh_ref,
        "GitHub App refresh credential",
    )
    refreshed = refresh_user_access_token(
        client_id=client_id,
        refresh_token=current_refresh_token,
        client_secret=client_secret,
        login_base=login_base,
        opener=opener,
        now=now,
        timeout_seconds=timeout_seconds,
    )
    rotated = refreshed.refresh_token != current_refresh_token
    if rotated:
        secrets.replace_secret_file(
            refresh_ref,
            "GitHub App refresh credential",
            refreshed.refresh_token,
        )
    return LocalUserAccessToken(
        access_token=refreshed.access_token,
        expires_at=refreshed.expires_at,
        refresh_token=refreshed.refresh_token,
        refresh_expires_at=refreshed.refresh_expires_at,
        scope=refreshed.scope,
        token_type=refreshed.token_type,
        refresh_rotated=rotated,
        refresh_credential_ref=str(Path(refresh_ref).expanduser()),
    )


def refresh_user_access_token(
    *,
    client_id: str,
    refresh_token: str,
    client_secret: str | None = None,
    login_base: str = token_contract.DEFAULT_GITHUB_WEB_BASE,
    opener: Callable[..., Any] | None = None,
    now: datetime | None = None,
    timeout_seconds: float = 30.0,
) -> LocalUserAccessToken:
    """Exchange a GitHub App refresh token for a user access token."""

    selected_now = _ensure_utc(now or datetime.now(timezone.utc))
    params = {
        "client_id": _required_string(client_id, "client_id"),
        "grant_type": token_contract.GITHUB_OAUTH_REFRESH_GRANT_TYPE,
        "refresh_token": _required_string(refresh_token, "refresh_token"),
    }
    if client_secret and client_secret.strip():
        params["client_secret"] = client_secret.strip()
    request = urllib.request.Request(
        _oauth_token_url(login_base),
        data=urllib.parse.urlencode(params).encode("utf-8"),
        headers={
            "Accept": token_contract.GITHUB_JSON_ACCEPT,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": token_contract.GITHUB_APP_USER_AGENT,
        },
        method="POST",
    )
    payload = _issue_request(request, opener=opener, timeout_seconds=timeout_seconds)
    error_code = str(payload.get("error") or "").strip()
    if error_code:
        description = str(payload.get("error_description") or error_code)
        raise GitHubUserTokenResponseError(description, error_code=error_code)
    return LocalUserAccessToken(
        access_token=_required_string(payload.get("access_token"), "access_token"),
        expires_at=_expires_from_seconds(
            payload.get("expires_in"),
            now=selected_now,
            label="expires_in",
        ),
        refresh_token=_required_string(payload.get("refresh_token"), "refresh_token"),
        refresh_expires_at=_expires_from_seconds(
            payload.get("refresh_token_expires_in"),
            now=selected_now,
            label="refresh_token_expires_in",
        ),
        scope=str(payload.get("scope") or ""),
        token_type=str(payload.get("token_type") or "bearer"),
    )


def _issue_request(
    request: urllib.request.Request,
    *,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    selected_opener = opener or urlopen
    try:
        with selected_opener(request, timeout=timeout_seconds) as response:
            return _parse_json(response.read())
    except urllib.error.HTTPError as exc:
        body = _read_error_body(exc)
        raise GitHubUserTokenResponseError(
            "GitHub App user-token refresh failed",
            status=exc.code,
            body=body,
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubUserTokenError(
            f"GitHub App user-token refresh failed: {exc.reason}"
        ) from exc


def _oauth_token_url(login_base: str) -> str:
    base = str(login_base or token_contract.DEFAULT_GITHUB_WEB_BASE).strip().rstrip("/")
    if not base:
        raise GitHubUserTokenError("GitHub web URL is required")
    return f"{base}{token_contract.GITHUB_OAUTH_ACCESS_TOKEN_PATH}"


def _parse_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError as exc:
        raise GitHubUserTokenError("GitHub App user-token response is not JSON") from exc
    if not isinstance(payload, dict):
        raise GitHubUserTokenError("GitHub App user-token response must be an object")
    return payload


def _required_string(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise GitHubUserTokenError(f"{label} is required")
    return text


def _expires_from_seconds(value: Any, *, now: datetime, label: str) -> datetime:
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise GitHubUserTokenError(f"{label} must be a positive integer") from exc
    if seconds <= 0:
        raise GitHubUserTokenError(f"{label} must be a positive integer")
    return _ensure_utc(now) + timedelta(seconds=seconds)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


__all__ = [
    "GitHubUserTokenError",
    "GitHubUserTokenResponseError",
    "LocalUserAccessToken",
    "refresh_from_machine_config",
    "refresh_user_access_token",
    "urlopen",
]
