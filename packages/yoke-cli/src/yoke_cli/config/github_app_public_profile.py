"""Authoritative public GitHub App profile discovery for machine clients."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_cli.config import github_app_public_profile_discovery as discovery
from yoke_cli.config import github_app_public_profile_values as profile_values
from yoke_cli.config import machine_config
from yoke_cli.config.github_app_public_profile_discovery import (
    GitHubAppPublicProfileError,
)
from yoke_contracts import github_app_tokens
from yoke_contracts.machine_config import schema as machine_contract
from yoke_contracts.github_app_public import (
    GITHUB_APP_API_URL_ENV,
    GITHUB_APP_CLIENT_ID_ENV,
    GITHUB_APP_ID_ENV,
    GITHUB_APP_SLUG_ENV,
    GITHUB_APP_WEB_URL_ENV,
    GitHubAppPublicProfile,
)


CLIENT_ID_ENV = GITHUB_APP_CLIENT_ID_ENV
APP_SLUG_ENV = GITHUB_APP_SLUG_ENV
APP_ID_ENV = GITHUB_APP_ID_ENV
API_URL_ENV = GITHUB_APP_API_URL_ENV
WEB_URL_ENV = GITHUB_APP_WEB_URL_ENV

_PROFILE_FIELDS = profile_values.PROFILE_FIELDS
_PROFILE_ENVS = profile_values.PROFILE_ENVS
_HEALTH_TIMEOUT_SECONDS = discovery.HEALTH_TIMEOUT_SECONDS
PROFILE_SOURCE_SERVICE = machine_contract.GITHUB_PROFILE_SOURCE_SERVICE
PROFILE_SOURCE_LOCAL_EXPLICIT = machine_contract.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT
PROFILE_SOURCE_LOCAL_PRODUCT = machine_contract.GITHUB_PROFILE_SOURCE_LOCAL_PRODUCT


_NoRedirectHandler = discovery._NoRedirectHandler
_urlopen = discovery.DEFAULT_URLOPEN


def resolve(
    *,
    service_api_url: str | None,
    client_id: str | None = None,
    app_slug: str | None = None,
    app_id: int | str | None = None,
    api_url: str | None = None,
    web_url: str | None = None,
    opener: Callable[..., Any] | None = None,
) -> GitHubAppPublicProfile:
    """Resolve one atomic profile: explicit, environment, then service health."""
    explicit = {
        "client_id": client_id,
        "app_slug": app_slug,
        "app_id": app_id,
        "api_url": api_url,
        "web_url": web_url,
    }
    if _any_present(explicit):
        return _parse_complete(explicit, source="explicit arguments")

    environment = {
        field: os.environ.get(env_name) for field, env_name in _PROFILE_ENVS.items()
    }
    if _any_present(environment):
        return _parse_complete(environment, source="environment")

    if not str(service_api_url or "").strip():
        raise GitHubAppPublicProfileError(
            "the selected HTTPS Yoke service URL is unavailable"
        )
    return fetch(str(service_api_url), opener=opener)


_validated_service_root = discovery.validated_service_root


def fetch(
    service_api_url: str,
    *,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = _HEALTH_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> GitHubAppPublicProfile:
    """Fetch a credential-free, redirect-denied health advertisement."""
    return discovery.fetch(
        service_api_url,
        opener=opener or _urlopen,
        timeout_seconds=timeout_seconds,
        monotonic=monotonic,
    )


def infer_service_api_url(
    config_path: str | Path | None = None,
    *,
    selected: str | None = None,
) -> str | None:
    """Return an explicit or selected HTTPS service, or None for local."""
    if str(selected or "").strip():
        return _validated_service_root(str(selected))
    return selected_https_service_api_url(config_path)


def selected_https_service_api_url(
    config_path: str | Path | None = None,
) -> str | None:
    """Return the exact active HTTPS service, or None for an explicit local transport."""
    try:
        connection = machine_config.active_connection(config_path)
    except (
        machine_config.MachineConfigError,
        machine_contract.MachineConfigContractError,
    ) as exc:
        raise GitHubAppPublicProfileError(
            "the selected Yoke connection is unavailable or invalid"
        ) from exc
    transport = str(connection.get("transport") or "")
    if transport == machine_contract.DEFAULT_TRANSPORT:
        return None
    if transport != machine_contract.TRANSPORT_HTTPS:
        raise GitHubAppPublicProfileError(
            "the selected Yoke connection has an unsupported transport"
        )
    api_url = str(connection.get("api_url") or "").strip()
    if not api_url:
        raise GitHubAppPublicProfileError(
            "the selected HTTPS Yoke connection has no API URL"
        )
    return _validated_service_root(api_url)


as_metadata = profile_values.as_metadata
service_metadata = profile_values.service_metadata
local_explicit_metadata = profile_values.local_explicit_metadata


def bundled_local_product_profile() -> GitHubAppPublicProfile:
    """Return the release-owned local product App identity, typed atomically."""

    values = github_app_tokens.local_product_profile_values()
    if not isinstance(values, Mapping):
        raise GitHubAppPublicProfileError(
            "the baseline product GitHub App is unavailable in this Yoke release"
        )
    return _parse_complete(values, source="bundled local product profile")


def local_product_metadata() -> dict[str, Any]:
    """Return machine-config metadata for the bundled local product App."""

    return {
        **as_metadata(bundled_local_product_profile()),
        "profile_source": PROFILE_SOURCE_LOCAL_PRODUCT,
    }


def assert_config_matches(
    github: Mapping[str, Any],
    profile: GitHubAppPublicProfile,
) -> None:
    """Refuse cached authorization created for any other App profile."""
    expected = as_metadata(profile)
    actual = {field: github.get(field) for field in _PROFILE_FIELDS}
    if actual == expected:
        return
    raise GitHubAppPublicProfileError(
        "the saved machine GitHub authorization belongs to a different Yoke "
        "GitHub App profile; run `yoke github disconnect`, then reconnect "
        "against the selected Yoke service"
    )


def resolve_and_match(
    github: Mapping[str, Any],
    *,
    service_api_url: str | None,
    opener: Callable[..., Any] | None = None,
) -> GitHubAppPublicProfile:
    if not str(service_api_url or "").strip():
        raise GitHubAppPublicProfileError(
            "the selected HTTPS Yoke service URL is unavailable"
        )
    selected_service = _validated_service_root(str(service_api_url))
    _assert_service_provenance(github, selected_service)
    profile = fetch(selected_service, opener=opener)
    assert_config_matches(github, profile)
    return profile


def resolve_selected_and_match(
    github: Mapping[str, Any],
    *,
    config_path: str | Path | None,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
    opener: Callable[..., Any] | None = None,
) -> GitHubAppPublicProfile:
    """Match HTTPS services by health and local dispatch by its saved profile."""
    selected = assert_selected_provenance(
        github,
        config_path=config_path,
        service_api_url=service_api_url,
        local_connection_selected=local_connection_selected,
    )
    if selected is not None:
        return resolve_and_match(
            github,
            service_api_url=selected,
            opener=opener,
        )

    profile = (
        bundled_local_product_profile()
        if github.get("profile_source") == PROFILE_SOURCE_LOCAL_PRODUCT
        else resolve(
            service_api_url=None,
            client_id=github.get("client_id"),
            app_slug=github.get("app_slug"),
            app_id=github.get("app_id"),
            api_url=github.get("api_url"),
            web_url=github.get("web_url"),
            opener=opener,
        )
    )
    assert_config_matches(github, profile)
    return profile


def assert_selected_provenance(
    github: Mapping[str, Any],
    *,
    config_path: str | Path | None,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
) -> str | None:
    """Require the cached profile's source to match the active transport."""

    if local_connection_selected and str(service_api_url or "").strip():
        raise GitHubAppPublicProfileError(
            "a local Yoke connection cannot also select an HTTPS service"
        )
    if local_connection_selected:
        _assert_local_provenance(github)
        return None
    if str(service_api_url or "").strip():
        selected = _validated_service_root(str(service_api_url))
        _assert_service_provenance(github, selected)
        return selected
    try:
        connection = machine_config.active_connection(config_path)
    except (
        machine_config.MachineConfigError,
        machine_contract.MachineConfigContractError,
    ) as exc:
        raise GitHubAppPublicProfileError(
            "the selected Yoke connection is unavailable"
        ) from exc
    transport = str(connection.get("transport") or "")
    if transport == machine_contract.TRANSPORT_HTTPS:
        selected = _validated_service_root(str(connection.get("api_url") or ""))
        _assert_service_provenance(github, selected)
        return selected
    if transport != machine_contract.DEFAULT_TRANSPORT:
        raise GitHubAppPublicProfileError(
            "the selected Yoke connection has an unsupported transport"
        )
    _assert_local_provenance(github)
    return None


def _assert_service_provenance(
    github: Mapping[str, Any],
    service_api_url: str,
) -> None:
    source = github.get("profile_source")
    saved_service = str(github.get("profile_service_api_url") or "")
    if (
        source == PROFILE_SOURCE_SERVICE
        and saved_service
        and _validated_service_root(saved_service) == service_api_url
    ):
        return
    raise GitHubAppPublicProfileError(
        "the saved GitHub App profile is not bound to the selected Yoke "
        "service; reconnect GitHub against this exact service"
    )


def _assert_local_provenance(github: Mapping[str, Any]) -> None:
    if github.get("profile_source") in {
        PROFILE_SOURCE_LOCAL_EXPLICIT,
        PROFILE_SOURCE_LOCAL_PRODUCT,
    } and github.get("profile_service_api_url") in (None, ""):
        return
    raise GitHubAppPublicProfileError(
        "the saved GitHub App profile is not authorized for local Yoke; "
        "reconnect with the bundled product App or all five explicit fields"
    )


_any_present = profile_values.any_present
_parse_complete = profile_values.parse_complete


__all__ = [
    "API_URL_ENV",
    "APP_ID_ENV",
    "APP_SLUG_ENV",
    "CLIENT_ID_ENV",
    "GitHubAppPublicProfileError",
    "PROFILE_SOURCE_LOCAL_EXPLICIT",
    "PROFILE_SOURCE_LOCAL_PRODUCT",
    "PROFILE_SOURCE_SERVICE",
    "WEB_URL_ENV",
    "as_metadata",
    "bundled_local_product_profile",
    "assert_selected_provenance",
    "assert_config_matches",
    "fetch",
    "infer_service_api_url",
    "local_explicit_metadata",
    "local_product_metadata",
    "resolve",
    "resolve_and_match",
    "resolve_selected_and_match",
    "service_metadata",
    "selected_https_service_api_url",
]
