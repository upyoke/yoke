"""Typed results and shared parsing for GitHub App token services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from typing import Any, Mapping

from yoke_contracts.timestamps import InvalidInstant, as_utc, parse_instant, utc_now


class GitHubAppTokenError(RuntimeError):
    """A GitHub App token operation could not complete."""


class GitHubAppTokenResponseError(GitHubAppTokenError):
    """GitHub returned an error response during a token exchange."""

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


class GitHubAppTokenUnavailableError(GitHubAppTokenError):
    """GitHub could not be reached, or did not answer within the time limit."""


class GitHubAppTokenResponseSizeError(GitHubAppTokenError):
    """A token response exceeded the bounded JSON envelope."""


class GitHubAppTokenResponseDecodeError(GitHubAppTokenError):
    """A token response was not valid UTF-8 or JSON."""


@dataclass(frozen=True)
class InstallationToken:
    """Short-lived bearer token minted for one GitHub App installation."""

    token: str = field(repr=False)
    expires_at: datetime
    issued_at: datetime | None = None
    permissions: Mapping[str, str] = field(default_factory=dict)
    repository_selection: str = ""
    repositories: tuple[str, ...] = ()

    def usable_at(
        self,
        at: datetime | None = None,
        *,
        skew_seconds: int = 60,
    ) -> bool:
        selected = ensure_utc(utc_now() if at is None else at)
        return ensure_utc(self.expires_at) > selected + timedelta(seconds=skew_seconds)


@dataclass(frozen=True)
class UserAccessToken:
    """Short-lived token minted from GitHub App user authorization."""

    access_token: str = field(repr=False)
    expires_at: datetime
    refresh_token: str = field(repr=False)
    refresh_expires_at: datetime
    scope: str = ""
    token_type: str = "bearer"


def ensure_utc(value: datetime) -> datetime:
    return as_utc(value)


def require_nonempty_string(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise GitHubAppTokenError(f"{label} is required")
    return text


def parse_github_datetime(value: Any, label: str) -> datetime:
    try:
        return parse_instant(value)
    except InvalidInstant as exc:
        raise GitHubAppTokenError(
            f"{label} is not a valid GitHub timestamp: {exc}"
        ) from exc


def expires_at_from_seconds(value: Any, *, now: datetime, label: str) -> datetime:
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise GitHubAppTokenError(f"{label} must be a positive integer") from exc
    if seconds <= 0:
        raise GitHubAppTokenError(f"{label} must be a positive integer")
    return ensure_utc(now) + timedelta(seconds=seconds)


def parse_json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError as exc:
        raise GitHubAppTokenError(f"{label} response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise GitHubAppTokenError(f"{label} response must be a JSON object")
    return payload


__all__ = [
    "GitHubAppTokenError",
    "GitHubAppTokenResponseDecodeError",
    "GitHubAppTokenResponseError",
    "GitHubAppTokenResponseSizeError",
    "GitHubAppTokenUnavailableError",
    "InstallationToken",
    "UserAccessToken",
    "ensure_utc",
    "expires_at_from_seconds",
    "parse_github_datetime",
    "parse_json_object",
    "require_nonempty_string",
    "utc_now",
]
