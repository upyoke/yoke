"""GitHub pull-request create via bearer-token REST.

Sibling of :mod:`yoke_core.domain.github_secrets_rest` /
:mod:`yoke_core.domain.github_variables_rest` for the repo-level
``github.*`` family: one POST to ``/repos/{owner}/{repo}/pulls`` so
agents open PRs with no host GitHub CLI binary.

Token resolution flows through ``resolve_project_github_auth`` at the
caller — never through host GitHub CLI credentials.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
)


def create_pull_request(
    repo: str,
    *,
    title: str,
    head: str,
    base: str,
    body: Optional[str] = None,
    draft: bool = False,
    token: str,
) -> Dict[str, Any]:
    """Open a pull request ``head`` -> ``base`` on ``repo``.

    Returns ``{"number": int, "url": str}`` from the created PR. Raises
    :class:`yoke_core.domain.gh_rest_transport.RestTransportError`
    (or a subclass) on terminal failure, including a malformed create
    response missing the PR number.
    """
    payload: Dict[str, Any] = {
        "title": title,
        "head": head,
        "base": base,
        "draft": bool(draft),
    }
    if body is not None:
        payload["body"] = body

    request = RestRequest(
        method="POST",
        path=f"/repos/{repo}/pulls",
        body=payload,
    )
    response = request_with_retry(request, token=token)
    response_body = response.body if isinstance(response.body, dict) else {}
    number = response_body.get("number")
    if not isinstance(number, int) or number <= 0:
        raise RestTransportError(
            f"create-PR response for {repo!r} missing pull-request number",
            status=response.status,
        )
    return {
        "number": number,
        "url": str(response_body.get("html_url") or ""),
    }


__all__ = ["create_pull_request"]
