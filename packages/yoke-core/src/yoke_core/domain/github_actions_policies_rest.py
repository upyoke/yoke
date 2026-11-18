"""GitHub repository Actions policy REST helpers.

Bearer-token siblings of :mod:`yoke_core.domain.github_merge_queue_rest`
for the declared ``actions_policies`` surface. Actions policies are
GitHub's workflow execution protections (``/repos/{owner}/{repo}/actions/
policies``); an event rule there is what lets a public repository keep
running ``pull_request_target`` workflows.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.gh_rest_transport import RestRequest, request_with_retry

_PAGE_SIZE = 100


def _policies_path(owner: str, repo: str) -> str:
    return f"/repos/{owner}/{repo}/actions/policies"


def list_repository_policies(
    owner: str, repo: str, *, token: str,
) -> list[dict[str, Any]]:
    """List the repository's own policies, not inherited org/enterprise ones.

    Summaries only; :func:`get_policy` carries conditions and rules.
    """
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=_policies_path(owner, repo),
                query={
                    "per_page": str(_PAGE_SIZE),
                    "page": str(page),
                    "has_parents": "false",
                },
            ),
            token=token,
        )
        body = response.body if isinstance(response.body, dict) else {}
        batch = [
            row for row in (body.get("policies") or []) if isinstance(row, dict)
        ]
        rows.extend(
            row for row in batch if row.get("source_type") in (None, "Repository")
        )
        if len(batch) < _PAGE_SIZE:
            return rows
        page += 1


def get_policy(
    owner: str, repo: str, policy_id: int, *, token: str,
) -> dict[str, Any]:
    """Return one policy including its conditions and rules."""
    response = request_with_retry(
        RestRequest(
            method="GET",
            path=f"{_policies_path(owner, repo)}/{int(policy_id)}",
        ),
        token=token,
    )
    return response.body if isinstance(response.body, dict) else {}


def create_policy(
    owner: str, repo: str, body: Mapping[str, Any], *, token: str,
) -> dict[str, Any]:
    """Create a repository policy from the declared body."""
    response = request_with_retry(
        RestRequest(method="POST", path=_policies_path(owner, repo), body=dict(body)),
        token=token,
    )
    return response.body if isinstance(response.body, dict) else {}


def update_policy(
    owner: str,
    repo: str,
    policy_id: int,
    body: Mapping[str, Any],
    *,
    token: str,
) -> dict[str, Any]:
    """Replace a repository policy with the declared body (idempotent PUT)."""
    response = request_with_retry(
        RestRequest(
            method="PUT",
            path=f"{_policies_path(owner, repo)}/{int(policy_id)}",
            body=dict(body),
        ),
        token=token,
    )
    return response.body if isinstance(response.body, dict) else {}


def delete_policy(owner: str, repo: str, policy_id: int, *, token: str) -> None:
    """Delete a repository policy the declaration does not name."""
    request_with_retry(
        RestRequest(
            method="DELETE",
            path=f"{_policies_path(owner, repo)}/{int(policy_id)}",
        ),
        token=token,
    )


__all__ = [
    "create_policy",
    "delete_policy",
    "get_policy",
    "list_repository_policies",
    "update_policy",
]
