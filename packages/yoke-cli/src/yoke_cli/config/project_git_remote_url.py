"""Credential-free source URL policy for project Git operations."""

from __future__ import annotations

import urllib.parse

from yoke_contracts import github_origin
from yoke_cli.config.project_onboard_support import ProjectOnboardError


def clean_remote_url(url: str, *, web_url: str | None = None) -> str:
    """Return a credential-free HTTPS URL for a GitHub or public Git remote."""

    raw = str(url or "").strip()
    endpoint = github_origin.validate_github_web_endpoint(web_url)
    try:
        repository = github_origin.normalize_github_repository(
            raw, web_url=endpoint.base_url,
        )
    except github_origin.GitHubApiOriginError:
        return _clean_public_https_remote(raw, configured_origin=endpoint.origin)
    return endpoint.url(f"/{repository}.git")


def is_configured_github_remote(
    url: str, *, web_url: str | None = None,
) -> bool:
    """Whether ``url`` names a repo on the exact configured GitHub origin."""

    endpoint = github_origin.validate_github_web_endpoint(web_url)
    try:
        github_origin.normalize_github_repository(
            url, web_url=endpoint.base_url,
        )
    except github_origin.GitHubApiOriginError:
        return False
    return True


def _clean_public_https_remote(raw: str, *, configured_origin: str) -> str:
    """Validate a non-GitHub source without enabling credential fallback."""

    error = (
        "repository must be a credential-free HTTPS clone URL or a configured "
        "GitHub repository reference"
    )
    if not raw or "\\" in raw or any(
        char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F
        for char in raw
    ):
        raise ProjectOnboardError(error)
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ProjectOnboardError(error) from exc
    decoded_path = urllib.parse.unquote(parsed.path)
    configured_host = str(
        urllib.parse.urlsplit(configured_origin).hostname or ""
    ).casefold()
    host = str(parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.strip("/")
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in decoded_path)
        or "\\" in decoded_path
        or any(part in {".", ".."} for part in decoded_path.split("/"))
        or (host == "github.com" and configured_host != "github.com")
    ):
        raise ProjectOnboardError(error)
    try:
        normalized_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ProjectOnboardError("repository hostname is invalid") from exc
    authority = (
        f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    )
    if port is not None:
        authority = f"{authority}:{port}"
    return urllib.parse.urlunsplit(("https", authority, parsed.path, "", ""))


__all__ = ["clean_remote_url", "is_configured_github_remote"]
