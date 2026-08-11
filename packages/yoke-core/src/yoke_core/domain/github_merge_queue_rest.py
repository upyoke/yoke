"""GitHub merge-queue ruleset + repo-setting REST helpers.

Bearer-token siblings of :mod:`yoke_core.domain.github_environments_rest`
for the declared merge-queue surface: read active branch rules, list/get/
create/update repository rulesets, and patch ``allow_auto_merge``.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    request_with_retry,
)


def fetch_branch_rules(
    owner: str, repo: str, branch: str, *, token: str,
) -> list[dict[str, Any]]:
    """Return active rules for ``branch`` (includes merge_queue parameters)."""
    response = request_with_retry(
        RestRequest(
            method="GET",
            path=f"/repos/{owner}/{repo}/rules/branches/{branch}",
        ),
        token=token,
    )
    body = response.body if isinstance(response.body, list) else []
    return [row for row in body if isinstance(row, dict)]


def fetch_repository(
    owner: str, repo: str, *, token: str,
) -> dict[str, Any]:
    """Return the repository record (includes ``allow_auto_merge``)."""
    response = request_with_retry(
        RestRequest(method="GET", path=f"/repos/{owner}/{repo}"),
        token=token,
    )
    return response.body if isinstance(response.body, dict) else {}


def list_rulesets(
    owner: str, repo: str, *, token: str,
) -> list[dict[str, Any]]:
    """List repository rulesets (id + name; details need :func:`get_ruleset`)."""
    response = request_with_retry(
        RestRequest(method="GET", path=f"/repos/{owner}/{repo}/rulesets"),
        token=token,
    )
    body = response.body if isinstance(response.body, list) else []
    return [row for row in body if isinstance(row, dict)]


def get_ruleset(
    owner: str, repo: str, ruleset_id: int, *, token: str,
) -> dict[str, Any]:
    """Return one ruleset including bypass actors and full rule parameters."""
    response = request_with_retry(
        RestRequest(
            method="GET",
            path=f"/repos/{owner}/{repo}/rulesets/{int(ruleset_id)}",
        ),
        token=token,
    )
    return response.body if isinstance(response.body, dict) else {}


def create_ruleset(
    owner: str, repo: str, body: Mapping[str, Any], *, token: str,
) -> dict[str, Any]:
    """Create a repository ruleset from the declared body."""
    response = request_with_retry(
        RestRequest(
            method="POST",
            path=f"/repos/{owner}/{repo}/rulesets",
            body=dict(body),
        ),
        token=token,
    )
    return response.body if isinstance(response.body, dict) else {}


def update_ruleset(
    owner: str,
    repo: str,
    ruleset_id: int,
    body: Mapping[str, Any],
    *,
    token: str,
) -> dict[str, Any]:
    """Replace a repository ruleset with the declared body (idempotent PUT)."""
    response = request_with_retry(
        RestRequest(
            method="PUT",
            path=f"/repos/{owner}/{repo}/rulesets/{int(ruleset_id)}",
            body=dict(body),
        ),
        token=token,
    )
    return response.body if isinstance(response.body, dict) else {}


def patch_allow_auto_merge(
    owner: str, repo: str, *, enabled: bool, token: str,
) -> dict[str, Any]:
    """Set repository ``allow_auto_merge`` via PATCH."""
    response = request_with_retry(
        RestRequest(
            method="PATCH",
            path=f"/repos/{owner}/{repo}",
            body={"allow_auto_merge": bool(enabled)},
        ),
        token=token,
    )
    return response.body if isinstance(response.body, dict) else {}


def find_ruleset_id_by_name(
    rulesets: Sequence[Mapping[str, Any]], name: str,
) -> Optional[int]:
    """Return the numeric id for ``name``, or None when absent."""
    for row in rulesets:
        if str(row.get("name") or "") == name:
            raw = row.get("id")
            if isinstance(raw, int):
                return raw
            if isinstance(raw, str) and raw.isdigit():
                return int(raw)
    return None


__all__ = [
    "create_ruleset",
    "fetch_branch_rules",
    "fetch_repository",
    "find_ruleset_id_by_name",
    "get_ruleset",
    "list_rulesets",
    "patch_allow_auto_merge",
    "update_ruleset",
]
