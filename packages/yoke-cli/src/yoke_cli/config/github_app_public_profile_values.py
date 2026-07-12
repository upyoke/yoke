"""Validation and machine-config projection for public GitHub App profiles."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_cli.config.github_app_public_profile_discovery import (
    GitHubAppPublicProfileError,
    validated_service_root,
)
from yoke_contracts.github_app_public import (
    GITHUB_APP_API_URL_ENV,
    GITHUB_APP_CLIENT_ID_ENV,
    GITHUB_APP_ID_ENV,
    GITHUB_APP_SLUG_ENV,
    GITHUB_APP_WEB_URL_ENV,
    GitHubAppPublicProfile,
    parse_github_app_advertisement,
)
from yoke_contracts.machine_config import schema as machine_contract

PROFILE_FIELDS = ("client_id", "app_slug", "app_id", "api_url", "web_url")
PROFILE_ENVS = {
    "client_id": GITHUB_APP_CLIENT_ID_ENV,
    "app_slug": GITHUB_APP_SLUG_ENV,
    "app_id": GITHUB_APP_ID_ENV,
    "api_url": GITHUB_APP_API_URL_ENV,
    "web_url": GITHUB_APP_WEB_URL_ENV,
}


def any_present(values: Mapping[str, Any]) -> bool:
    return any(value not in (None, "") for value in values.values())


def parse_complete(
    values: Mapping[str, Any],
    *,
    source: str,
) -> GitHubAppPublicProfile:
    missing = [field for field in PROFILE_FIELDS if values.get(field) in (None, "")]
    if missing:
        rendered = ", ".join(field.replace("_", " ") for field in missing)
        raise GitHubAppPublicProfileError(
            f"GitHub App {source} must provide one complete profile; missing: "
            f"{rendered}"
        )
    if isinstance(values.get("app_id"), bool):
        raise GitHubAppPublicProfileError("GitHub App id must be a positive integer")
    payload = {"available": True, **dict(values)}
    try:
        parsed = parse_github_app_advertisement(payload)
    except (TypeError, ValueError) as exc:
        raise GitHubAppPublicProfileError(
            f"GitHub App {source} are invalid: {exc}"
        ) from exc
    if not isinstance(parsed, GitHubAppPublicProfile):
        raise GitHubAppPublicProfileError(
            f"GitHub App {source} did not provide an available profile"
        )
    return parsed


def as_metadata(profile: GitHubAppPublicProfile) -> dict[str, Any]:
    return {field: getattr(profile, field) for field in PROFILE_FIELDS}


def service_metadata(
    profile: GitHubAppPublicProfile,
    *,
    service_api_url: str,
) -> dict[str, Any]:
    metadata = as_metadata(profile)
    metadata.update(
        {
            "profile_source": machine_contract.GITHUB_PROFILE_SOURCE_SERVICE,
            "profile_service_api_url": validated_service_root(service_api_url),
        }
    )
    return metadata


def local_explicit_metadata(profile: GitHubAppPublicProfile) -> dict[str, Any]:
    return {
        **as_metadata(profile),
        "profile_source": machine_contract.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
    }
