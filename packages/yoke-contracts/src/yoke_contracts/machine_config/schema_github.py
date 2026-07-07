"""Machine-level GitHub credential contract."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_config.credential_sources import (
    CREDENTIAL_KIND_TOKEN_FILE,
    GITHUB_CREDENTIAL_KINDS,
)
from yoke_contracts.machine_config.schema_projects import (
    ValidationIssue,
    _error,
    _is_nonempty_str,
)

GITHUB_CONFIG_KEY = "github"
DEFAULT_GITHUB_API_URL = "https://api.github.com"
GITHUB_ALLOWED_KEYS = frozenset({
    "api_url",
    "credential_source",
    "verified_login",
    "verified_user_id",
    "scopes",
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
    if not _is_nonempty_str(entry.get("api_url")):
        issues.append(_error(
            "github_api_url_required",
            "github.api_url must be a non-empty string",
            path="github.api_url",
        ))
    source = entry.get("credential_source")
    if not isinstance(source, Mapping):
        issues.append(_error(
            "github_credential_source_required",
            "github.credential_source must be an object",
            path="github.credential_source",
        ))
    else:
        issues.extend(_validate_github_credential_source(source))
    if "verified_login" in entry and not _is_nonempty_str(entry.get("verified_login")):
        issues.append(_error(
            "github_verified_login_invalid",
            "github.verified_login must be a non-empty string",
            path="github.verified_login",
        ))
    if "verified_user_id" in entry and not isinstance(entry.get("verified_user_id"), int):
        issues.append(_error(
            "github_verified_user_id_invalid",
            "github.verified_user_id must be an integer",
            path="github.verified_user_id",
        ))
    scopes = entry.get("scopes")
    if scopes is not None:
        if not isinstance(scopes, list) or not all(isinstance(item, str) for item in scopes):
            issues.append(_error(
                "github_scopes_invalid",
                "github.scopes must be a list of strings",
                path="github.scopes",
            ))
    return issues


def _validate_github_credential_source(
    source: Mapping[str, Any],
) -> list[ValidationIssue]:
    kind = source.get("kind")
    if not _is_nonempty_str(kind) or str(kind) not in GITHUB_CREDENTIAL_KINDS:
        return [_error(
            "github_credential_kind_invalid",
            f"github credential_source.kind must be one of {sorted(GITHUB_CREDENTIAL_KINDS)}",
            path="github.credential_source.kind",
        )]
    if kind == CREDENTIAL_KIND_TOKEN_FILE and not _is_nonempty_str(source.get("path")):
        return [_error(
            "github_credential_token_file_path_required",
            "github token_file credential_source requires path",
            path="github.credential_source.path",
        )]
    return []
