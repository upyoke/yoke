"""GitHub issue accessibility for epic validation through the shared REST transport."""

from __future__ import annotations

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)


def _issue_accessible_via_rest(repo: str, issue_num: str, *, token: str) -> bool:
    """Return True when ``GET /repos/<owner>/<name>/issues/<n>`` responds 200.

    Routes via the canonical bearer-token REST transport.
    """
    if not repo or not issue_num:
        return False
    try:
        owner, name = split_repo(repo)
    except ValueError:
        return False
    req = RestRequest(method="GET", path=f"/repos/{owner}/{name}/issues/{issue_num}")
    try:
        request_with_retry(req, token=token)
    except RestTransportError:
        return False
    return True
