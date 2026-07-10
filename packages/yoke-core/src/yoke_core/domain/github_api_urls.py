"""Exact-origin URL construction for GitHub REST callers."""

from __future__ import annotations

import os
from typing import Mapping
import urllib.parse
import urllib.request

from yoke_contracts.github_origin import (
    GitHubApiEndpoint,
    require_same_github_origin,
    validate_github_api_endpoint,
)
from yoke_core.domain.github_app_control_plane import GITHUB_APP_API_URL_ENV
from yoke_core.domain.github_app_dispatch_context import LOCAL_API_ENDPOINT


def active_api_endpoint(default_base: str) -> GitHubApiEndpoint:
    """Resolve the local-dispatch, control-plane, or caller default endpoint."""
    contextual = LOCAL_API_ENDPOINT.get()
    if contextual is not None:
        return contextual
    configured = os.environ.get(GITHUB_APP_API_URL_ENV, "").strip()
    return validate_github_api_endpoint(configured or default_base)


def build_url(
    path: str,
    query: Mapping[str, str],
    *,
    default_base: str,
) -> str:
    """Build one REST URL and reject absolute URLs on another origin."""
    endpoint = active_api_endpoint(default_base)
    if path.startswith("http://") or path.startswith("https://"):
        base = path
        require_same_github_origin(base, endpoint)
    else:
        base = _relative_url(endpoint, path)
    if not query:
        return base
    encoded = "&".join(
        f"{urllib.request.quote(str(key), safe='')}="
        f"{urllib.request.quote(str(value), safe='')}"
        for key, value in query.items()
    )
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{encoded}"


def _relative_url(endpoint: GitHubApiEndpoint, path: str) -> str:
    suffix = path if path.startswith("/") else f"/{path}"
    api_path = urllib.parse.urlsplit(endpoint.base_url).path.rstrip("/")
    if suffix == "/graphql" and api_path == "/api/v3":
        return f"{endpoint.origin}/api/graphql"
    return endpoint.url(suffix)


__all__ = ["active_api_endpoint", "build_url"]
