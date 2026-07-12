"""Bounded domain validation for cached GitHub App access metadata."""

from __future__ import annotations

import re
from typing import Any, Mapping
import unicodedata

from yoke_contracts import git_ref_name, github_origin


MAX_LOGIN_CHARS = 100
MAX_APP_SLUG_CHARS = 100
MAX_REPOSITORY_NAME_CHARS = 100
MAX_PERMISSION_COUNT = 64
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")
_APP_SLUG = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")
_PERMISSION_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}")
ACCOUNT_TYPES = frozenset({"Enterprise", "Organization", "User"})
REPOSITORY_SELECTIONS = frozenset({"all", "selected"})
PERMISSION_LEVELS = frozenset({"read", "write"})


class GitHubAppSnapshotError(ValueError):
    """GitHub returned metadata outside its bounded public domain."""


def user_login(value: Any, label: str = "user.login") -> str:
    return _matched(value, label, maximum=MAX_LOGIN_CHARS, pattern=_LOGIN)


def app_slug(value: Any, label: str = "installation.app_slug") -> str:
    return _matched(
        value, label, maximum=MAX_APP_SLUG_CHARS, pattern=_APP_SLUG,
    )


def account_type(value: Any) -> str:
    selected = _text(value, "installation.account.type", maximum=32)
    if selected not in ACCOUNT_TYPES:
        raise GitHubAppSnapshotError(
            "installation.account.type is not a supported GitHub account type"
        )
    return selected


def repository_selection(value: Any) -> str:
    selected = _text(value, "installation.repository_selection", maximum=16)
    if selected not in REPOSITORY_SELECTIONS:
        raise GitHubAppSnapshotError(
            "installation.repository_selection is invalid"
        )
    return selected


def repository_full_name(value: Any) -> str:
    selected = _text(value, "repository.full_name", maximum=202)
    try:
        normalized = github_origin.normalize_github_repository(selected)
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubAppSnapshotError(str(exc)) from exc
    owner, name = normalized.split("/", 1)
    if (
        normalized != selected
        or len(owner) > MAX_LOGIN_CHARS
        or len(name) > MAX_REPOSITORY_NAME_CHARS
    ):
        raise GitHubAppSnapshotError("repository.full_name is invalid")
    return selected


def default_branch(value: Any) -> str:
    if value in (None, ""):
        return ""
    selected = _text(
        value, "repository.default_branch",
        maximum=git_ref_name.MAX_BRANCH_NAME_CHARS,
    )
    if not git_ref_name.is_valid_branch(selected):
        raise GitHubAppSnapshotError("repository.default_branch is invalid")
    return selected


def permissions(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or len(value) > MAX_PERMISSION_COUNT:
        raise GitHubAppSnapshotError("installation.permissions is invalid")
    normalized: dict[str, str] = {}
    for key, level in value.items():
        if not isinstance(key, str) or _PERMISSION_KEY.fullmatch(key) is None:
            raise GitHubAppSnapshotError("installation permission key is invalid")
        if level not in PERMISSION_LEVELS:
            raise GitHubAppSnapshotError("installation permission level is invalid")
        normalized[key] = level
    return normalized


def _matched(
    value: Any, label: str, *, maximum: int, pattern: re.Pattern[str],
) -> str:
    selected = _text(value, label, maximum=maximum)
    if pattern.fullmatch(selected) is None:
        raise GitHubAppSnapshotError(f"{label} is invalid")
    return selected


def _text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise GitHubAppSnapshotError(f"{label} must be a string")
    if not value or value != value.strip() or len(value) > maximum:
        raise GitHubAppSnapshotError(f"{label} is invalid")
    if any(
        ord(char) < 32
        or ord(char) == 127
        or unicodedata.category(char) in {"Cc", "Cf"}
        for char in value
    ):
        raise GitHubAppSnapshotError(f"{label} contains control characters")
    return value


__all__ = [
    "ACCOUNT_TYPES", "GitHubAppSnapshotError", "PERMISSION_LEVELS",
    "REPOSITORY_SELECTIONS", "account_type", "app_slug", "default_branch",
    "permissions", "repository_full_name", "repository_selection", "user_login",
]
