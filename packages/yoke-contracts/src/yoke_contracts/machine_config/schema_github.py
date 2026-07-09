"""Machine-level GitHub App connection contract."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_config.schema_projects import (
    ValidationIssue,
    _error,
    _is_nonempty_str,
)

GITHUB_CONFIG_KEY = "github"
DEFAULT_GITHUB_API_URL = "https://api.github.com"
GITHUB_AUTH_KIND_USER_AUTHORIZATION = "github_app_user_authorization"
GITHUB_AUTH_STATUSES = frozenset({"authorized", "pending", "revoked"})
GITHUB_REPOSITORY_SELECTIONS = frozenset({"all", "selected"})
GITHUB_ALLOWED_KEYS = frozenset({
    "api_url",
    "app_slug",
    "app_id",
    "client_id",
    "authorization",
    "installations",
    "repositories",
})
GITHUB_AUTH_ALLOWED_KEYS = frozenset({
    "kind",
    "refresh_credential_ref",
    "github_user_id",
    "login",
    "status",
    "scopes",
    "permissions",
})
GITHUB_INSTALLATION_ALLOWED_KEYS = frozenset({
    "installation_id",
    "account_id",
    "account_login",
    "account_type",
    "repository_selection",
    "suspended",
    "permissions",
})
GITHUB_REPOSITORY_ALLOWED_KEYS = frozenset({
    "repository_id",
    "full_name",
    "default_branch",
    "installation_id",
})


def github_config(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a defensive copy of the configured GitHub block."""
    raw = (payload or {}).get(GITHUB_CONFIG_KEY)
    return dict(raw) if isinstance(raw, Mapping) else {}


def normalize_github_payload(
    raw: Mapping[str, Any],
    normalized: dict[str, Any],
) -> None:
    entry = raw.get(GITHUB_CONFIG_KEY)
    if isinstance(entry, Mapping):
        normalized[GITHUB_CONFIG_KEY] = dict(entry)


def has_github_config(payload: Mapping[str, Any] | None) -> bool:
    """Whether the payload carries a GitHub machine capability block."""
    return bool(github_config(payload))


def validate_github_config(payload: Mapping[str, Any]) -> list[ValidationIssue]:
    """Validate the optional ``github`` machine capability block."""
    if GITHUB_CONFIG_KEY not in payload:
        return []
    entry = payload.get(GITHUB_CONFIG_KEY)
    if not isinstance(entry, Mapping):
        return [_error(
            "github_invalid",
            "github must be an object",
            path=GITHUB_CONFIG_KEY,
        )]
    issues: list[ValidationIssue] = []
    for key in sorted(set(entry) - GITHUB_ALLOWED_KEYS):
        issues.append(_error(
            "github_key_invalid",
            f"github does not support {key!r}",
            path=f"{GITHUB_CONFIG_KEY}.{key}",
        ))
    issues.extend(_validate_nonempty(entry, "api_url"))
    issues.extend(_validate_nonempty(entry, "app_slug"))
    issues.extend(_validate_nonempty(entry, "client_id"))
    if "app_id" in entry and not isinstance(entry.get("app_id"), int):
        issues.append(_error(
            "github_app_id_invalid",
            "github.app_id must be an integer",
            path="github.app_id",
        ))
    authorization = entry.get("authorization")
    if not isinstance(authorization, Mapping):
        issues.append(_error(
            "github_authorization_required",
            "github.authorization must be an object",
            path="github.authorization",
        ))
    else:
        issues.extend(_validate_github_authorization(authorization))
    issues.extend(_validate_installations(entry.get("installations")))
    issues.extend(_validate_repositories(entry.get("repositories")))
    return issues


def _validate_nonempty(
    entry: Mapping[str, Any],
    key: str,
    *,
    prefix: str = GITHUB_CONFIG_KEY,
) -> list[ValidationIssue]:
    if _is_nonempty_str(entry.get(key)):
        return []
    return [_error(
        f"{prefix.replace('.', '_')}_{key}_required",
        f"{prefix}.{key} must be a non-empty string",
        path=f"{prefix}.{key}",
    )]


def _validate_github_authorization(
    authorization: Mapping[str, Any],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    prefix = "github.authorization"
    for key in sorted(set(authorization) - GITHUB_AUTH_ALLOWED_KEYS):
        issues.append(_error(
            "github_authorization_key_invalid",
            f"{prefix} does not support {key!r}",
            path=f"{prefix}.{key}",
        ))
    kind = authorization.get("kind")
    if kind != GITHUB_AUTH_KIND_USER_AUTHORIZATION:
        issues.append(_error(
            "github_authorization_kind_invalid",
            f"{prefix}.kind must be {GITHUB_AUTH_KIND_USER_AUTHORIZATION!r}",
            path=f"{prefix}.kind",
        ))
    issues.extend(_validate_nonempty(
        authorization,
        "refresh_credential_ref",
        prefix=prefix,
    ))
    status = authorization.get("status")
    if status not in GITHUB_AUTH_STATUSES:
        issues.append(_error(
            "github_authorization_status_invalid",
            f"{prefix}.status must be one of {sorted(GITHUB_AUTH_STATUSES)}",
            path=f"{prefix}.status",
        ))
    if "login" in authorization and not _is_nonempty_str(authorization.get("login")):
        issues.append(_error(
            "github_authorization_login_invalid",
            f"{prefix}.login must be a non-empty string",
            path=f"{prefix}.login",
        ))
    if (
        "github_user_id" in authorization
        and not isinstance(authorization.get("github_user_id"), int)
    ):
        issues.append(_error(
            "github_authorization_user_id_invalid",
            f"{prefix}.github_user_id must be an integer",
            path=f"{prefix}.github_user_id",
        ))
    scopes = authorization.get("scopes")
    if scopes is not None and (
        not isinstance(scopes, list)
        or not all(isinstance(item, str) for item in scopes)
    ):
        issues.append(_error(
            "github_authorization_scopes_invalid",
            f"{prefix}.scopes must be a list of strings",
            path=f"{prefix}.scopes",
        ))
    permissions = authorization.get("permissions")
    if permissions is not None and not isinstance(permissions, Mapping):
        issues.append(_error(
            "github_authorization_permissions_invalid",
            f"{prefix}.permissions must be an object",
            path=f"{prefix}.permissions",
        ))
    return issues


def _validate_installations(value: Any) -> list[ValidationIssue]:
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
                "github_installation_invalid",
                f"{prefix} must be an object",
                path=prefix,
            ))
            continue
        issues.extend(_validate_installation(item, prefix=prefix))
    return issues


def _validate_installation(
    installation: Mapping[str, Any],
    *,
    prefix: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in sorted(set(installation) - GITHUB_INSTALLATION_ALLOWED_KEYS):
        issues.append(_error(
            "github_installation_key_invalid",
            f"{prefix} does not support {key!r}",
            path=f"{prefix}.{key}",
        ))
    if not isinstance(installation.get("installation_id"), int):
        issues.append(_error(
            "github_installation_id_invalid",
            f"{prefix}.installation_id must be an integer",
            path=f"{prefix}.installation_id",
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
            f"{prefix}.repository_selection must be one of {sorted(GITHUB_REPOSITORY_SELECTIONS)}",
            path=f"{prefix}.repository_selection",
        ))
    if "permissions" in installation and not isinstance(
        installation.get("permissions"),
        Mapping,
    ):
        issues.append(_error(
            "github_installation_permissions_invalid",
            f"{prefix}.permissions must be an object",
            path=f"{prefix}.permissions",
        ))
    if "suspended" in installation and not isinstance(installation.get("suspended"), bool):
        issues.append(_error(
            "github_installation_suspended_invalid",
            f"{prefix}.suspended must be a boolean",
            path=f"{prefix}.suspended",
        ))
    return issues


def _validate_repositories(value: Any) -> list[ValidationIssue]:
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
                "github_repository_invalid",
                f"{prefix} must be an object",
                path=prefix,
            ))
            continue
        issues.extend(_validate_repository(item, prefix=prefix))
    return issues


def _validate_repository(
    repository: Mapping[str, Any],
    *,
    prefix: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in sorted(set(repository) - GITHUB_REPOSITORY_ALLOWED_KEYS):
        issues.append(_error(
            "github_repository_key_invalid",
            f"{prefix} does not support {key!r}",
            path=f"{prefix}.{key}",
        ))
    if not isinstance(repository.get("repository_id"), int):
        issues.append(_error(
            "github_repository_id_invalid",
            f"{prefix}.repository_id must be an integer",
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
        and not isinstance(repository.get("installation_id"), int)
    ):
        issues.append(_error(
            "github_repository_installation_id_invalid",
            f"{prefix}.installation_id must be an integer",
            path=f"{prefix}.installation_id",
        ))
    return issues
