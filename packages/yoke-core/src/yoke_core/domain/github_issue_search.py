"""Permissions and readable payloads for GitHub's combined issue/PR search."""

from __future__ import annotations

import shlex
from typing import Any

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.gh_rest_transport import RestTransportError


def issue_search_permissions(query: str) -> dict[str, str]:
    """Use one grant for a known type filter, both when both types can match."""
    try:
        terms = set(shlex.split(query, posix=False))
    except ValueError:
        terms = set()  # GitHub owns malformed-query errors.
    issues = bool(terms & {"is:issue", "type:issue"})
    prs = bool(terms & {"is:pr", "type:pr"})
    if issues and not prs:
        return dict(GITHUB_ISSUES_READ_PERMISSION_LEVELS)
    if prs and not issues:
        return dict(GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS)
    return {
        **GITHUB_ISSUES_READ_PERMISSION_LEVELS,
        **GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS,
    }


def parse_issue_search_items(payload: Any) -> list[dict[str, Any]]:
    """Distinguish a complete empty search from hidden or partial results."""
    def unreadable(field: str):
        raise RestTransportError(
            f"issue_search_unreadable: {field}; repair: verify the GitHub App "
            "grants Issues or Pull requests read access for the search, then retry"
        )

    if not isinstance(payload, dict):
        unreadable("response is not an object")
    if type(payload.get("total_count")) is not int or payload["total_count"] < 0:
        unreadable("total_count is missing or malformed")
    if payload.get("incomplete_results") is not False:
        unreadable("incomplete_results is hidden or the search is incomplete")
    items = payload.get("items")
    if not isinstance(items, list):
        unreadable("items is missing or malformed")
    for item in items:
        if not isinstance(item, dict):
            unreadable("items contains a hidden or malformed result")
        if type(item.get("number")) is not int or item["number"] <= 0:
            unreadable("result number is missing or malformed")
        if not isinstance(item.get("title"), str):
            unreadable("result title is missing or malformed")
        if item.get("state") not in ("open", "closed"):
            unreadable("result state is missing or malformed")
    return items
