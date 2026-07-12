"""Validation for GitHub App installation settings links."""

from __future__ import annotations

import urllib.parse

from yoke_contracts import github_origin


def validated_settings_url(
    value: str,
    *,
    web_url: str,
    installation_id: int,
    account_login: str,
) -> str:
    """Return GitHub's exact personal/org installation URL when it is safe."""
    if (
        isinstance(installation_id, bool)
        or not isinstance(installation_id, int)
        or installation_id <= 0
    ):
        raise github_origin.GitHubApiOriginError(
            "GitHub App installation id must be a positive integer"
        )
    expected = github_origin.validate_github_web_endpoint(web_url)
    candidate = github_origin.validate_github_web_endpoint(value)
    if candidate.origin != expected.origin:
        raise github_origin.GitHubApiOriginError(
            "GitHub App installation settings URL crossed the configured web origin"
        )
    parsed = urllib.parse.urlsplit(candidate.base_url)
    encoded_path = parsed.path.casefold()
    if any(marker in encoded_path for marker in ("%2e", "%2f", "%5c")):
        raise github_origin.GitHubApiOriginError(
            "GitHub App installation settings URL contains encoded path separators"
        )
    decoded_path = urllib.parse.unquote(parsed.path)
    if "\\" in decoded_path or any(
        part in {".", ".."} for part in decoded_path.split("/")
    ):
        raise github_origin.GitHubApiOriginError(
            "GitHub App installation settings URL contains an unsafe path"
        )
    personal_path = f"/settings/installations/{installation_id}"
    organization_path = (
        f"/organizations/{account_login}/settings/installations/{installation_id}"
    )
    if decoded_path not in {personal_path, organization_path}:
        raise github_origin.GitHubApiOriginError(
            "GitHub App installation settings URL is not canonical for the account"
        )
    return candidate.base_url


__all__ = ["validated_settings_url"]
