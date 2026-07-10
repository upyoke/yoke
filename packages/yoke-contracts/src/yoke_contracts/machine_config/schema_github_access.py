"""Cached GitHub App installation and repository config validation."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_config.schema_projects import (
    ValidationIssue,
    _error,
    _is_nonempty_str,
)

GITHUB_REPOSITORY_SELECTIONS = frozenset({"all", "selected"})
GITHUB_INSTALLATION_ALLOWED_KEYS = frozenset({
    "installation_id", "account_id", "account_login", "account_type",
    "repository_selection", "suspended", "permissions",
})
GITHUB_REPOSITORY_ALLOWED_KEYS = frozenset({
    "repository_id", "full_name", "default_branch", "installation_id",
})


def validate_installations(value: Any) -> list[ValidationIssue]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [_error(
            "github_installations_invalid",
            "github.installations must be a list",
            path="github.installations",
        )]
    issues: list[ValidationIssue] = []
    for index, item in enumerate(value):
        prefix = f"github.installations.{index}"
        if not isinstance(item, Mapping):
            issues.append(_error(
                "github_installation_invalid", f"{prefix} must be an object",
                path=prefix,
            ))
            continue
        issues.extend(_validate_installation(item, prefix=prefix))
    return issues


def _validate_installation(
    installation: Mapping[str, Any], *, prefix: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in sorted(set(installation) - GITHUB_INSTALLATION_ALLOWED_KEYS):
        issues.append(_error(
            "github_installation_key_invalid",
            f"{prefix} does not support {key!r}", path=f"{prefix}.{key}",
        ))
    if not _positive_int(installation.get("installation_id")):
        issues.append(_error(
            "github_installation_id_invalid",
            f"{prefix}.installation_id must be a positive integer",
            path=f"{prefix}.installation_id",
        ))
    if "account_id" in installation and not _positive_int(
        installation.get("account_id")
    ):
        issues.append(_error(
            "github_installation_account_id_invalid",
            f"{prefix}.account_id must be a positive integer",
            path=f"{prefix}.account_id",
        ))
    if not _is_nonempty_str(installation.get("account_login")):
        issues.append(_error(
            "github_installation_account_login_required",
            f"{prefix}.account_login must be a non-empty string",
            path=f"{prefix}.account_login",
        ))
    selection = installation.get("repository_selection")
    if selection not in GITHUB_REPOSITORY_SELECTIONS:
        issues.append(_error(
            "github_installation_repository_selection_invalid",
            f"{prefix}.repository_selection must be one of "
            f"{sorted(GITHUB_REPOSITORY_SELECTIONS)}",
            path=f"{prefix}.repository_selection",
        ))
    if "permissions" in installation and not isinstance(
        installation.get("permissions"), Mapping,
    ):
        issues.append(_error(
            "github_installation_permissions_invalid",
            f"{prefix}.permissions must be an object",
            path=f"{prefix}.permissions",
        ))
    if "suspended" in installation and not isinstance(
        installation.get("suspended"), bool,
    ):
        issues.append(_error(
            "github_installation_suspended_invalid",
            f"{prefix}.suspended must be a boolean",
            path=f"{prefix}.suspended",
        ))
    return issues


def validate_repositories(value: Any) -> list[ValidationIssue]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [_error(
            "github_repositories_invalid",
            "github.repositories must be a list",
            path="github.repositories",
        )]
    issues: list[ValidationIssue] = []
    for index, item in enumerate(value):
        prefix = f"github.repositories.{index}"
        if not isinstance(item, Mapping):
            issues.append(_error(
                "github_repository_invalid", f"{prefix} must be an object",
                path=prefix,
            ))
            continue
        issues.extend(_validate_repository(item, prefix=prefix))
    return issues


def _validate_repository(
    repository: Mapping[str, Any], *, prefix: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in sorted(set(repository) - GITHUB_REPOSITORY_ALLOWED_KEYS):
        issues.append(_error(
            "github_repository_key_invalid",
            f"{prefix} does not support {key!r}", path=f"{prefix}.{key}",
        ))
    if not _positive_int(repository.get("repository_id")):
        issues.append(_error(
            "github_repository_id_invalid",
            f"{prefix}.repository_id must be a positive integer",
            path=f"{prefix}.repository_id",
        ))
    if not _is_nonempty_str(repository.get("full_name")):
        issues.append(_error(
            "github_repository_full_name_required",
            f"{prefix}.full_name must be a non-empty string",
            path=f"{prefix}.full_name",
        ))
    if (
        "installation_id" in repository
        and not _positive_int(repository.get("installation_id"))
    ):
        issues.append(_error(
            "github_repository_installation_id_invalid",
            f"{prefix}.installation_id must be a positive integer",
            path=f"{prefix}.installation_id",
        ))
    return issues


def _positive_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


__all__ = ["validate_installations", "validate_repositories"]
