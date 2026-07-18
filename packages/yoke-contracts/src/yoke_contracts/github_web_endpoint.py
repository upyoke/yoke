"""Map canonical GitHub API bases to their browser endpoints."""

from __future__ import annotations

import urllib.parse


def github_web_url_from_api(api_url: str) -> str:
    """Return the canonical browser base paired with a GitHub API base."""
    from yoke_contracts.github_origin import (
        DEFAULT_GITHUB_API_URL,
        DEFAULT_GITHUB_WEB_URL,
        GitHubApiOriginError,
        validate_github_api_endpoint,
        validate_github_endpoint_pair,
    )

    endpoint = validate_github_api_endpoint(api_url)
    parsed = urllib.parse.urlsplit(endpoint.base_url)
    hostname = str(parsed.hostname or "")
    if endpoint.base_url == DEFAULT_GITHUB_API_URL:
        web_url = DEFAULT_GITHUB_WEB_URL
    elif hostname.startswith("api.") and hostname.endswith(".ghe.com"):
        authority = hostname.removeprefix("api.")
        if parsed.port is not None:
            authority = f"{authority}:{parsed.port}"
        web_url = f"https://{authority}"
    elif parsed.path.rstrip("/") == "/api/v3":
        web_url = endpoint.origin
    else:
        raise GitHubApiOriginError(
            "GitHub API URL must be a canonical GitHub Cloud, GitHub "
            "Enterprise Cloud data-residency, or GHES base"
        )
    return validate_github_endpoint_pair(api_url, web_url).web.base_url


__all__ = ["github_web_url_from_api"]
