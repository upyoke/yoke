"""Finding the pull request that already exists for a branch.

Two callers want two different answers from the same listing. A local merge
reuses a pull request it can still merge, so it asks only for open ones. A
queue landing has to converge on the pull request the queue already merged —
closed by the time a retry looks for it — so it asks for any state and
prefers an open one.

Keeping both here makes the difference explicit at the call site: reaching
for the open-only read where convergence is needed is what makes a retry
create a second pull request for a branch with nothing left to merge.

Seeing merged pull requests carries its own hazard, which is why the landing
read compares heads. A lane that committed again after its pull request
merged still matches that pull request by branch name, and converging on it
would bind the new head to the old merge commit — evidence naming work that
never landed. The listing already carries each row's head, so the comparison
costs nothing beyond the read the caller was making anyway.

Every read fails soft, returning ``(None, None)``; the caller decides what an
absent answer means.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS as PR_READ,
)

from yoke_core.domain import gh_rest_transport
from yoke_core.domain import standalone_item_merge_git as git
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


@dataclass(frozen=True)
class BranchListing:
    """The listing for one head branch, or why it could not be read.

    A caller deciding whether it is safe to move the branch cannot treat a
    listing it never got as a branch with no pull request: an auth failure,
    a transport failure, and a response that is not an array all look
    exactly like "nothing open" to a reader that only sees rows. ``error``
    is that distinction, and an empty ``rows`` beside an empty ``error`` is
    the genuine answer.
    """

    rows: tuple[dict[str, Any], ...] = ()
    error: str = ""

    @property
    def readable(self) -> bool:
        return not self.error


def list_branch_pull_requests(
    ctx: MergeContext, *, query: dict[str, str]
) -> BranchListing:
    """Read the branch's pull requests, naming a listing that did not happen.

    ``query`` carries the caller's filters, including ``base``: GitHub allows
    one open pull request per head AND base, so a listing filtered only by
    head can hold several rows targeting different branches, and the first
    of those is not necessarily the landing the caller is asking about.
    """
    try:
        auth = resolve_auth(ctx, required_permissions=PR_READ)
    except AuthResolutionFailed as exc:
        return BranchListing(error=f"pull request listing unavailable: {exc}")
    owner, repo = gh_rest_transport.split_repo(auth.repo)
    req = RestRequest(
        method="GET",
        path=f"/repos/{owner}/{repo}/pulls",
        query={"head": f"{owner}:{ctx.args.branch}", **query},
    )
    try:
        resp = request_with_retry(req, token=auth.token)
    except RestTransportError as exc:
        return BranchListing(error=f"pull request listing failed: {exc}")
    if not isinstance(resp.body, list):
        return BranchListing(
            error="pull request listing returned no array of pull requests"
        )
    rows: list[dict[str, Any]] = []
    for row in resp.body:
        if not isinstance(row, dict):
            # Dropping the entry would turn a malformed response into a
            # shorter listing, and a listing of one malformed entry into an
            # empty one — which reads as "this branch has no pull request".
            return BranchListing(
                error=(
                    "pull request listing carried an entry that is not a "
                    f"pull request object ({type(row).__name__})"
                )
            )
        rows.append(row)
    return BranchListing(rows=tuple(rows))


def base_ref(row: dict[str, Any]) -> Optional[str]:
    """The branch a listing row targets, or ``None`` when it does not say.

    A row whose ``base`` is absent, is not an object, or carries no ``ref``
    is not a row targeting some other branch — it is a row that did not
    answer. A caller that treats those the same reads a malformed response
    as "nothing is holding this branch".
    """
    base = row.get("base")
    if not isinstance(base, dict):
        return None
    return str(base.get("ref") or "").strip() or None


def _list_branch_prs(
    ctx: MergeContext, *, query: dict[str, str]
) -> list[dict[str, Any]]:
    """Pull requests whose head is the branch; an unread listing is empty."""
    return list(list_branch_pull_requests(ctx, query=query).rows)


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


def _head_sha(row: dict[str, Any]) -> str:
    """The commit the pull request's head branch pointed at."""
    head = row.get("head")
    return str((head or {}).get("sha") or "").strip() if isinstance(head, dict) else ""


def _carries_unlanded_work(ctx: MergeContext, lane_head: str) -> bool:
    """Whether ``lane_head`` holds anything the base branch does not.

    A head that differs from what a pull request merged is not by itself work
    left over. A lane fast-forwarded onto the base after its own merge points
    at the merge commit — a different sha that the base branch nonetheless
    contains — and calling that "commits beyond the pull request that merged
    it" sends close-out off to open a second pull request for work that has
    already landed.

    A lane rebased after its own merge is the same mistake reached a harder
    way: it points at fresh copies of the merged commits, which no ancestry
    read can attribute to the merge that took them. Patch identity can, so a
    head the base does not contain is asked once more whether any commit it
    carries is missing from the base — counting a lane-only merge as missing,
    because a merge carries no patch for that read to compare.

    Without a checkout to read, the answer stays the conservative one: treat
    the difference as unlanded work rather than converge on a merge this
    process cannot confirm. An unreadable patch comparison answers the same
    way, for the same reason.
    """
    if not ctx.repo_root:
        return True
    if git.is_landed(ctx.repo_root, lane_head, ctx.args.target):
        return False
    base = git.current_base_ref(ctx.repo_root, ctx.args.target)
    return git.unlanded_commits(ctx.repo_root, lane_head, base) != ()


def find_landable_pull_request(
    ctx: MergeContext, *, lane_head: str = "",
) -> Tuple[Optional[str], Optional[str], str]:
    """The pull request this landing may use, and why it may not use one.

    A merged pull request answers here where :func:`find_existing_pr` sees
    nothing, which is what lets a landing re-entered after the queue merged
    converge on that pull request instead of trying to open another. Any
    state means the listing can hold several, so it asks for the most
    recently updated first and falls back to that row.

    Convergence on a merged pull request is allowed only when it covers
    ``lane_head``: a lane carrying commits beyond what merged has not landed,
    and the third element names that refusal so the caller opens a fresh
    landing rather than recording the old merge commit as this head's.
    """
    rows = _list_branch_prs(
        ctx,
        query={"state": "all", "sort": "updated", "direction": "desc"},
    )
    if not rows:
        return None, None, ""
    still_open = [row for row in rows if str(row.get("state") or "") == "open"]
    if still_open:
        url, number = _identify(still_open[0])
        return url, number, ""
    newest = rows[0]
    merged_head = _head_sha(newest)
    if (
        lane_head
        and newest.get("merged_at")
        and merged_head != lane_head
        and _carries_unlanded_work(ctx, lane_head)
    ):
        _, number = _identify(newest)
        return None, None, (
            f"pull request {number or '?'} merged head "
            f"{merged_head[:12] or 'unknown'}, not the lane head "
            f"{lane_head[:12]}"
        )
    url, number = _identify(newest)
    return url, number, ""


__all__ = ["find_existing_pr", "find_landable_pull_request"]
