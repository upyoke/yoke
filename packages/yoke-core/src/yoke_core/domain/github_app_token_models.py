"""Typed results and shared parsing for GitHub App token services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Mapping


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


@dataclass(frozen=True)
class InstallationToken:
    """Short-lived bearer token minted for one GitHub App installation."""

    token: str
    expires_at: datetime
    permissions: Mapping[str, str] = field(default_factory=dict)
    repository_selection: str = ""
    repositories: tuple[str, ...] = ()

    def usable_at(
        self,
        at: datetime | None = None,
        *,
        skew_seconds: int = 60,
    ) -> bool:
        selected = ensure_utc(at or utc_now())
        return self.expires_at > selected + timedelta(seconds=skew_seconds)


@dataclass(frozen=True)
class UserAccessToken:
    """Short-lived token minted from GitHub App user authorization."""

    access_token: str
    expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    scope: str = ""
    token_type: str = "bearer"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def require_nonempty_string(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise GitHubAppTokenError(f"{label} is required")
    return text


def parse_github_datetime(value: Any, label: str) -> datetime:
    raw = require_nonempty_string(value, label)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GitHubAppTokenError(f"{label} is not a valid GitHub timestamp") from exc
    return ensure_utc(parsed)


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
    "GitHubAppTokenResponseError",
    "InstallationToken",
    "UserAccessToken",
    "ensure_utc",
    "expires_at_from_seconds",
    "parse_github_datetime",
    "parse_json_object",
    "require_nonempty_string",
    "utc_now",
]
