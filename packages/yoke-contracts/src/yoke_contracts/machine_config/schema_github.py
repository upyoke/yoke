"""Machine-level GitHub App connection contract."""

from __future__ import annotations

import urllib.parse
from typing import Any, Mapping

from yoke_contracts import github_app_snapshot

from yoke_contracts.github_origin import (
    DEFAULT_GITHUB_API_URL as DEFAULT_GITHUB_API_URL,
    DEFAULT_GITHUB_WEB_URL,
    GitHubApiOriginError,
    validate_github_api_endpoint,
    validate_github_endpoint_pair,
    validate_github_web_endpoint,
)
from yoke_contracts.github_app_tokens import (
    GITHUB_AUTH_KIND_USER_AUTHORIZATION,
    GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
    GITHUB_PROFILE_SOURCE_LOCAL_PRODUCT,
    GITHUB_PROFILE_SOURCE_SERVICE,
)
from yoke_contracts.machine_config.schema_projects import (
    ValidationIssue,
    _error,
    _is_nonempty_str,
)
from yoke_contracts.machine_config.schema_github_access import (
    validate_installations,
    validate_repositories,
)

GITHUB_CONFIG_KEY = "github"
GITHUB_AUTH_STATUSES = frozenset({"authorized", "pending", "revoked"})
GITHUB_PROFILE_SOURCES = frozenset({
    GITHUB_PROFILE_SOURCE_SERVICE,
    GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
    GITHUB_PROFILE_SOURCE_LOCAL_PRODUCT,
})
GITHUB_ALLOWED_KEYS = frozenset({
    "api_url",
    "web_url",
    "app_slug",
    "app_id",
    "client_id",
    "profile_source",
    "profile_service_api_url",
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
    issues.extend(_validate_endpoint(entry, "api_url", validate_github_api_endpoint))
    if "web_url" in entry:
        issues.extend(_validate_nonempty(entry, "web_url"))
        issues.extend(_validate_endpoint(entry, "web_url", validate_github_web_endpoint))
    issues.extend(_validate_endpoint_pair(entry))
    issues.extend(_validate_nonempty(entry, "app_slug"))
    if _is_nonempty_str(entry.get("app_slug")):
        try:
            github_app_snapshot.app_slug(entry.get("app_slug"), "github.app_slug")
        except github_app_snapshot.GitHubAppSnapshotError:
            issues.append(_error(
                "github_app_slug_invalid",
                "github.app_slug may contain only bounded letters, numbers, and hyphens",
                path="github.app_slug",
            ))
    issues.extend(_validate_nonempty(entry, "client_id"))
    issues.extend(_validate_profile_provenance(entry))
    if "app_id" not in entry:
        issues.append(_error(
            "github_app_id_required",
            "github.app_id must be a positive integer",
            path="github.app_id",
        ))
    elif (
        isinstance(entry.get("app_id"), bool)
        or not isinstance(entry.get("app_id"), int)
        or int(entry.get("app_id")) <= 0
    ):
        issues.append(_error(
            "github_app_id_invalid",
            "github.app_id must be a positive integer",
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
    issues.extend(validate_installations(entry.get("installations")))
    issues.extend(validate_repositories(entry.get("repositories")))
    return issues


def _validate_profile_provenance(
    entry: Mapping[str, Any],
) -> list[ValidationIssue]:
    source = entry.get("profile_source")
    if source not in GITHUB_PROFILE_SOURCES:
        return [_error(
            "github_profile_source_invalid",
            "github.profile_source must be 'service', 'local_product', or "
            "'local_explicit'; "
            "reconnect GitHub to bind the saved profile",
            path="github.profile_source",
        )]
    service_url = entry.get("profile_service_api_url")
    if source in {
        GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
        GITHUB_PROFILE_SOURCE_LOCAL_PRODUCT,
    }:
        if service_url not in (None, ""):
            return [_error(
                "github_profile_service_unexpected",
                "github.profile_service_api_url is only valid for service profiles",
                path="github.profile_service_api_url",
            )]
        return []
    if not _is_nonempty_str(service_url):
        return [_error(
            "github_profile_service_required",
            "github.profile_service_api_url is required for a service profile",
            path="github.profile_service_api_url",
        )]
    parsed = urllib.parse.urlsplit(str(service_url))
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment
    ):
        return [_error(
            "github_profile_service_invalid",
            "github.profile_service_api_url must be a credential-free HTTPS URL",
            path="github.profile_service_api_url",
        )]
    return []


def _validate_endpoint(
    entry: Mapping[str, Any],
    key: str,
    validator: Any,
) -> list[ValidationIssue]:
    value = entry.get(key)
    if not _is_nonempty_str(value):
        return []
    try:
        validator(str(value))
    except GitHubApiOriginError as exc:
        return [_error(
            f"github_{key}_invalid",
            str(exc).replace("API URL", f"{key.replace('_', ' ')}"),
            path=f"github.{key}",
        )]
    return []


def _validate_endpoint_pair(entry: Mapping[str, Any]) -> list[ValidationIssue]:
    if not _is_nonempty_str(entry.get("api_url")):
        return []
    if "web_url" in entry and not _is_nonempty_str(entry.get("web_url")):
        return []
    try:
        validate_github_endpoint_pair(
            str(entry["api_url"]),
            str(entry.get("web_url") or DEFAULT_GITHUB_WEB_URL),
        )
    except GitHubApiOriginError as exc:
        return [_error(
            "github_endpoint_pair_invalid", str(exc), path="github",
        )]
    return []


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
    if "login" in authorization:
        try:
            github_app_snapshot.user_login(
                authorization.get("login"), f"{prefix}.login",
            )
        except github_app_snapshot.GitHubAppSnapshotError:
            issues.append(_error(
                "github_authorization_login_invalid",
                f"{prefix}.login is invalid",
                path=f"{prefix}.login",
            ))
    if (
        "github_user_id" in authorization
        and (
            isinstance(authorization.get("github_user_id"), bool)
            or not isinstance(authorization.get("github_user_id"), int)
            or int(authorization.get("github_user_id")) <= 0
        )
    ):
        issues.append(_error(
            "github_authorization_user_id_invalid",
            f"{prefix}.github_user_id must be a positive integer",
            path=f"{prefix}.github_user_id",
        ))
    return issues
