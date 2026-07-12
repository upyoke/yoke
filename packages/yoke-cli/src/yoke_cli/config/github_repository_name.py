"""Exact GitHub repository-name validation shared by UI and REST writes."""

from __future__ import annotations

import re


MAX_LENGTH = 100
_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class GitHubRepositoryNameError(ValueError):
    """A repository name could be normalized or rejected by GitHub."""


def validated(value: object) -> str:
    """Return one exact stable name or reject it before any remote write."""

    if not isinstance(value, str) or value != value.strip():
        raise GitHubRepositoryNameError(
            "Repository names cannot start or end with whitespace."
        )
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise GitHubRepositoryNameError(
            "Repository names must be valid text."
        ) from exc
    if not value or len(value) > MAX_LENGTH or not _NAME.fullmatch(value):
        raise GitHubRepositoryNameError(
            f"Use 1-{MAX_LENGTH} letters, numbers, periods, hyphens, or underscores."
        )
    if value in {".", ".."} or value.casefold().endswith(".git"):
        raise GitHubRepositoryNameError(
            "Choose a repository name other than '.', '..', or a name ending in .git."
        )
    return value


def validation_error(value: str) -> str | None:
    """Return a short inline error, or None for an exact stable name."""

    try:
        validated(value)
    except GitHubRepositoryNameError as exc:
        return str(exc)
    return None


__all__ = [
    "GitHubRepositoryNameError",
    "MAX_LENGTH",
    "validated",
    "validation_error",
]
