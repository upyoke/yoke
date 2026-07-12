"""Canonical validation for GitHub App repository-binding metadata."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Mapping
import unicodedata

from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    normalize_github_repository,
)


GITHUB_ACCOUNT_LOGIN_MAX_CHARS = 39
GITHUB_IDENTIFIER_MAX_DIGITS = 20
GITHUB_REPOSITORY_FULL_NAME_MAX_CHARS = 140
GITHUB_BRANCH_MAX_BYTES = 255
GITHUB_PERMISSION_KEY_MAX_CHARS = 64
GITHUB_PERMISSION_MAX_ITEMS = 100
_ACCOUNT_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
_PERMISSION_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_ACCOUNT_TYPES = {"user": "User", "organization": "Organization"}
_REPOSITORY_SELECTIONS = frozenset({"all", "selected"})
_PERMISSION_LEVELS = frozenset({"read", "write"})
_INSTALLATION_STATUSES = frozenset({"active", "suspended"})
_FORBIDDEN_REF_CHARACTERS = frozenset("~^:?*[\\")


class GitHubBindingMetadataError(ValueError):
    """A GitHub response cannot be persisted as binding metadata."""


@dataclass(frozen=True)
class ValidatedGitHubBindingMetadata:
    """Canonical, persistence-safe metadata proven by the GitHub API."""

    installation_id: str
    account_id: str
    account_login: str
    account_type: str
    repository_selection: str
    permissions: Mapping[str, str]
    repository_id: str
    github_repo: str
    default_branch: str
    installation_status: str


def validate_binding_metadata(
    *,
    installation_id: Any,
    account_id: Any,
    account_login: Any,
    account_type: Any,
    repository_selection: Any,
    permissions: Mapping[str, Any],
    repository_id: Any,
    github_repo: Any,
    default_branch: Any,
    installation_status: Any,
) -> ValidatedGitHubBindingMetadata:
    """Return one canonical binding record or reject it before persistence."""

    return ValidatedGitHubBindingMetadata(
        installation_id=validate_identifier(installation_id, "installation id"),
        account_id=validate_identifier(account_id, "account id"),
        account_login=validate_account_login(account_login),
        account_type=validate_account_type(account_type),
        repository_selection=validate_repository_selection(repository_selection),
        permissions=validate_permissions(permissions),
        repository_id=validate_identifier(repository_id, "repository id"),
        github_repo=validate_repository_full_name(github_repo),
        default_branch=validate_default_branch(default_branch),
        installation_status=validate_installation_status(installation_status),
    )


def validate_identifier(value: Any, label: str) -> str:
    """Return one positive decimal GitHub database identifier."""

    if isinstance(value, bool):
        raise GitHubBindingMetadataError(f"GitHub {label} must be positive")
    try:
        selected = str(value or "").strip()
    except (TypeError, ValueError, OverflowError) as exc:
        raise GitHubBindingMetadataError(f"GitHub {label} must be positive") from exc
    if (
        len(selected) > GITHUB_IDENTIFIER_MAX_DIGITS
        or not selected.isascii()
        or not selected.isdecimal()
        or int(selected) <= 0
    ):
        raise GitHubBindingMetadataError(f"GitHub {label} must be positive")
    return selected


def validate_account_login(value: Any) -> str:
    """Return one bounded GitHub user or organization login."""

    selected = _exact_text(value, "account login")
    if (
        len(selected) > GITHUB_ACCOUNT_LOGIN_MAX_CHARS
        or _ACCOUNT_LOGIN.fullmatch(selected) is None
    ):
        raise GitHubBindingMetadataError("GitHub account login is invalid")
    return selected


def validate_account_type(value: Any) -> str:
    """Return GitHub's canonical User or Organization account type."""

    selected = _exact_text(value, "account type")
    canonical = _ACCOUNT_TYPES.get(selected.casefold())
    if canonical is None:
        raise GitHubBindingMetadataError("GitHub account type is invalid")
    return canonical


def validate_repository_selection(value: Any) -> str:
    """Return the exact GitHub App repository-selection mode."""

    selected = _exact_text(value, "repository selection")
    if selected not in _REPOSITORY_SELECTIONS:
        raise GitHubBindingMetadataError("GitHub repository selection is invalid")
    return selected


def validate_permissions(value: Mapping[str, Any]) -> Mapping[str, str]:
    """Return a bounded immutable GitHub App permission map."""

    if not isinstance(value, Mapping):
        raise GitHubBindingMetadataError("GitHub permissions must be an object")
    if len(value) > GITHUB_PERMISSION_MAX_ITEMS:
        raise GitHubBindingMetadataError("GitHub permissions are too large")
    validated: dict[str, str] = {}
    for raw_key, raw_level in value.items():
        key = _exact_text(raw_key, "permission key")
        level = _exact_text(raw_level, "permission level")
        if (
            len(key) > GITHUB_PERMISSION_KEY_MAX_CHARS
            or _PERMISSION_KEY.fullmatch(key) is None
            or level not in _PERMISSION_LEVELS
        ):
            raise GitHubBindingMetadataError("GitHub permission metadata is invalid")
        validated[key] = level
    return MappingProxyType(validated)


def validate_repository_full_name(value: Any) -> str:
    """Normalize one bounded GitHub repository reference to owner/name."""

    selected = _exact_text(value, "repository full name")
    if len(selected) > 512:
        raise GitHubBindingMetadataError("GitHub repository full name is too large")
    try:
        normalized = normalize_github_repository(selected)
    except GitHubApiOriginError as exc:
        raise GitHubBindingMetadataError(
            "GitHub repository full name is invalid"
        ) from exc
    if len(normalized) > GITHUB_REPOSITORY_FULL_NAME_MAX_CHARS:
        raise GitHubBindingMetadataError("GitHub repository full name is too large")
    return normalized


def validate_default_branch(value: Any) -> str:
    """Return a bounded branch accepted by Git's branch-ref grammar."""

    selected = _exact_text(value, "default branch")
    if len(selected) > GITHUB_BRANCH_MAX_BYTES:
        raise GitHubBindingMetadataError("GitHub default branch is too large")
    try:
        encoded = selected.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise GitHubBindingMetadataError("GitHub default branch is invalid") from exc
    if len(encoded) > GITHUB_BRANCH_MAX_BYTES:
        raise GitHubBindingMetadataError("GitHub default branch is too large")
    parts = selected.split("/")
    invalid = (
        selected == "@"
        or selected.startswith(("-", "/"))
        or selected.endswith(("/", "."))
        or ".." in selected
        or "//" in selected
        or "@{" in selected
        or any(character in _FORBIDDEN_REF_CHARACTERS for character in selected)
        or any(
            character.isspace() or unicodedata.category(character) in {"Cc", "Cf"}
            for character in selected
        )
        or any(
            not part or part.startswith(".") or part.casefold().endswith(".lock")
            for part in parts
        )
    )
    if invalid:
        raise GitHubBindingMetadataError("GitHub default branch is invalid")
    return selected


def validate_installation_status(value: Any) -> str:
    """Return a live GitHub installation state proven during binding."""

    selected = _exact_text(value, "installation status")
    if selected not in _INSTALLATION_STATUSES:
        raise GitHubBindingMetadataError("GitHub installation status is invalid")
    return selected


def _exact_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise GitHubBindingMetadataError(f"GitHub {label} is invalid")
    return value


__all__ = [
    "GitHubBindingMetadataError",
    "ValidatedGitHubBindingMetadata",
    "validate_account_login",
    "validate_account_type",
    "validate_binding_metadata",
    "validate_default_branch",
    "validate_identifier",
    "validate_installation_status",
    "validate_permissions",
    "validate_repository_full_name",
    "validate_repository_selection",
]
