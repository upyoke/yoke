"""Which pull request the merge that landed an item's work actually carried.

``items.merge_queue_pr_number`` is a marker naming the pull request an item
last armed, not frozen provenance. A lane whose commits reach the base under
a sibling pull request leaves its own one open forever, and every later
question -- the merge-group receipt, the landing observation, the next
close-out -- then asks that open pull request about a merge it never
performed and gets a correct "this never merged" back.

Close-out is the moment that can answer: it has already resolved the merge
the base actually holds this lane's work under, so the pull request that
merge carried is a read away. Repointing there is what keeps the marker
self-healing; the human-only repair in
:mod:`yoke_core.domain.item_merge_provenance_pull_request` stays for the
landings no close-out can resolve -- a fast-forward or squash that left no
merge commit to read, an unreadable checkout, an unreachable provider.

The carrier is read from a recorded fact rather than asserted. GitHub's own
listing of the pull requests a commit belongs to answers first, filtered to
the one whose recorded merge commit IS this merge, so an associated pull
request that merely contains the commit can never be mistaken for the
carrier. The merge commit's subject answers only when that listing cannot:
GitHub wrote that subject when it performed the merge, so it is the same
fact recorded in the one place still readable when the provider is not.
"""

from __future__ import annotations

import re
from typing import Any

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS as PR_READ,
)
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.domain.merge_queue_landing_pending import (
    record_landing_pull_request,
)
from yoke_core.engines.merge_worktree_pr_queue import resolve_auth_detail
from yoke_core.engines.merge_worktree_prepare import MergeContext

# What GitHub writes as the subject of a merge it performed for a pull
# request, on the ordinary merge route and on a merge-queue train alike.
_MERGE_SUBJECT = re.compile(r"\bMerge pull request #(\d+)\b")


def _same_sha(left: str, right: str) -> bool:
    a, b = left.strip().lower(), right.strip().lower()
    return bool(a) and a == b


def _recorded_carrier(ctx: MergeContext, merge_sha: str) -> tuple[str, str]:
    """The carrier GitHub recorded for ``merge_sha``, or why it did not."""
    auth, auth_err = resolve_auth_detail(ctx, PR_READ)
    if auth_err or auth is None:
        return "", f"pull request read unavailable: {auth_err}"
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/commits/{merge_sha}/pulls",
            ),
            token=auth.token,
        )
    except RestTransportError as exc:
        return "", f"pull request read for {merge_sha[:12]} failed: {exc}"
    listing: Any = response.body if isinstance(response.body, list) else []
    for entry in listing:
        if not isinstance(entry, dict):
            continue
        # A pull request is listed for every commit its head branch holds.
        # Only the one whose own recorded merge commit is this merge
        # performed it; the rest merely contain it.
        if _same_sha(str(entry.get("merge_commit_sha") or ""), merge_sha):
            number = str(entry.get("number") or "").strip()
            if number:
                return number, ""
    return "", (
        f"GitHub lists no pull request on {auth.repo} whose merge commit is "
        f"{merge_sha[:12]}"
    )


def _subject_carrier(ctx: MergeContext, merge_sha: str) -> str:
    """The carrier named in the merge commit's own subject, if any."""
    if not ctx.repo_root:
        return ""
    subject = git.git_out(ctx.repo_root, "log", "-1", "--format=%s", merge_sha)
    match = _MERGE_SUBJECT.search(subject)
    return match.group(1) if match else ""


def landing_carrier(ctx: MergeContext, merge_sha: str) -> tuple[str, str]:
    """The pull request ``merge_sha`` carried, with how it was established.

    Returns ``(pr_number, source)``, or ``("", reason)`` when neither the
    provider's record nor the merge commit itself names one.
    """
    if not merge_sha:
        return "", "no landing merge commit was resolved"
    recorded, recorded_error = _recorded_carrier(ctx, merge_sha)
    if recorded:
        return recorded, "GitHub's own record of the merge"
    from_subject = _subject_carrier(ctx, merge_sha)
    if from_subject:
        return from_subject, (
            f"the subject GitHub wrote on merge {merge_sha[:12]}, because "
            f"{recorded_error}"
        )
    return "", recorded_error


def repoint_to_landing_carrier(
    ctx: MergeContext,
    *,
    item_id: int,
    recorded_pr_number: str,
    merge_sha: str,
) -> str:
    """Point the item at the pull request its landing merge carried.

    Returns an advisory note for the caller's warnings, empty when the
    marker already names the carrier -- the ordinary landing, where the
    item's own pull request is the one that merged. The write is the same
    marker writer the merge boundary and the operator repair share, so a
    correction here can never be the weaker of the three: the superseded
    pull request's queue admission, landing stamp and observation row drop
    with the number they belonged to.

    Never raises. A landing is durable by the time this runs, so an
    unresolved carrier is reported rather than allowed to unwind it.
    """
    if not merge_sha or not item_id:
        return ""
    recorded = str(recorded_pr_number or "").strip()
    carrier, source = landing_carrier(ctx, merge_sha)
    if not carrier:
        return (
            f"landing pull request not verified for pull request {recorded}: "
            f"{source}. The marker still names pull request {recorded}; "
            "re-run the same close-out command once the read is possible, or "
            "repoint it with `yoke items merge-provenance operator-correct "
            "<PREFIX-N> --pr-number <N> --reason ...`"
        )
    if carrier == recorded:
        return ""
    error = record_landing_pull_request(int(item_id), carrier)
    if error:
        return (
            f"pull request marker still names {recorded}, but merge "
            f"{merge_sha[:12]} was carried by pull request {carrier} "
            f"({source}); the repoint write failed: {error}"
        )
    return (
        f"pull request marker repointed from {recorded} to {carrier}: the "
        f"base holds this lane's work under merge {merge_sha[:12]}, which "
        f"pull request {carrier} carried ({source}). Pull request {recorded} "
        "never merged this landing, so every later question now asks the one "
        "that did"
    )


__all__ = ["landing_carrier", "repoint_to_landing_carrier"]
