"""Explain the cached installation facts required for GitHub Fork creation."""

from __future__ import annotations

from typing import Any

from yoke_contracts import github_origin

UNVERIFIED = (
    "fork_access_unverified: Connect GitHub with `yoke github connect`, then "
    "review Fork again after installation access is refreshed."
)


def unavailable_reason(config: dict[str, Any], remote_url: str | None) -> str:
    """Return concrete unmet conditions; an empty reason means Fork is ready."""
    if not remote_url:
        return "fork_source_unresolved: Choose the source repository before reviewing Fork."
    try:
        endpoint = github_origin.validate_github_endpoint_pair(
            str(config.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
            str(config.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL),
        )
        if endpoint.deployment_kind != "github_cloud":
            return "fork_host_unsupported: Yoke Fork creation requires a github.com source."
        source = github_origin.normalize_github_repository(
            remote_url, web_url=endpoint.web.base_url,
        )
    except github_origin.GitHubApiOriginError:
        return "fork_source_invalid: Select a repository on the connected GitHub deployment."
    authorization = config.get("authorization")
    login = str(
        (authorization.get("login") or "") if isinstance(authorization, dict) else ""
    ).casefold()
    installations = [
        row for row in config.get("installations") or []
        if isinstance(row, dict) and not row.get("suspended")
    ]
    personal_all = any(
        str(row.get("account_type") or "").casefold() == "user"
        and str(row.get("account_login") or "").casefold() == login
        and row.get("repository_selection") == "all"
        and isinstance(row.get("permissions"), dict)
        and row["permissions"].get("contents") == "write"
        and row["permissions"].get("administration") == "write"
        for row in installations
    )
    source_access = any(
        str(repo.get("full_name") or "").casefold() == source.casefold()
        and any(
            row.get("installation_id") == repo.get("installation_id")
            and isinstance(row.get("permissions"), dict)
            and row["permissions"].get("contents") in {"read", "write"}
            and row["permissions"].get("administration") == "write"
            for row in installations
        )
        for repo in config.get("repositories") or [] if isinstance(repo, dict)
    )
    problems = []
    if not personal_all or not login:
        problems.append(
            "fork_destination_access_unavailable: Set the personal GitHub App "
            f"installation for {login or 'your authenticated account'} to All repositories "
            "with Contents: write and Administration: write; reconnect with "
            "`yoke github connect` to refresh access."
        )
    if not source_access:
        problems.append(
            f"fork_source_access_unavailable: Add {source} to a non-suspended GitHub "
            "App installation's selected repositories with Contents: read or write "
            "and Administration: write; reconnect with `yoke github connect` to refresh access."
        )
    return " ".join(problems)
