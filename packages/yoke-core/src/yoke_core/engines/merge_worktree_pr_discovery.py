"""Finding the pull request that already exists for a branch.

Two callers want two different answers from the same listing. A local merge
reuses a pull request it can still merge, so it asks only for open ones. A
queue landing has to converge on the pull request the queue already merged —
closed by the time a retry looks for it — so it asks for any state and
prefers an open one.

Keeping both here makes the difference explicit at the call site: reaching
for the open-only read where convergence is needed is what makes a retry
create a second pull request for a branch with nothing left to merge.

Every read fails soft, returning ``(None, None)``; the caller decides what an
absent answer means.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS as PR_READ,
)

from yoke_core.domain import gh_rest_transport
from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.engines.merge_worktree_pr_rest import (
    AuthResolutionFailed,
    resolve_auth,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


def _list_branch_prs(
    ctx: MergeContext, *, query: dict[str, str]
) -> list[dict[str, Any]]:
    """Pull requests whose head is the branch, under the caller's filters."""
    try:
        auth = resolve_auth(ctx, required_permissions=PR_READ)
    except AuthResolutionFailed:
        return []
    owner, repo = gh_rest_transport.split_repo(auth.repo)
    req = RestRequest(
        method="GET",
        path=f"/repos/{owner}/{repo}/pulls",
        query={"head": f"{owner}:{ctx.args.branch}", **query},
    )
    try:
        resp = request_with_retry(req, token=auth.token)
    except RestTransportError:
        return []
    rows = resp.body if isinstance(resp.body, list) else []
    return [row for row in rows if isinstance(row, dict)]


def _identify(row: dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """``(url, number)`` for one listing row, or ``(None, None)``."""
    url = str(row.get("html_url") or row.get("url") or "").strip()
    number = row.get("number")
    num_str = str(number).strip() if number is not None else ""
    if not url or not num_str:
        return None, None
    return url, num_str


def find_existing_pr(
    ctx: MergeContext,
) -> Tuple[Optional[str], Optional[str]]:
    """The branch's open pull request, or ``(None, None)``.

    No ordering is requested because GitHub allows only one open pull
    request per head and base, so the listing holds at most one row.
    """
    rows = _list_branch_prs(ctx, query={"state": "open"})
    return _identify(rows[0]) if rows else (None, None)


def find_branch_pull_request(
    ctx: MergeContext,
) -> Tuple[Optional[str], Optional[str]]:
    """The branch's pull request in any state, preferring one still open.

    A merged pull request answers here where :func:`find_existing_pr` sees
    nothing, which is what lets a landing re-entered after the queue merged
    converge on that pull request instead of trying to open another. Any
    state means the listing can hold several, so it asks for the most
    recently updated first and falls back to that row.
    """
    rows = _list_branch_prs(
        ctx,
        query={"state": "all", "sort": "updated", "direction": "desc"},
    )
    if not rows:
        return None, None
    still_open = [row for row in rows if str(row.get("state") or "") == "open"]
    return _identify((still_open or rows)[0])


__all__ = ["find_branch_pull_request", "find_existing_pr"]
