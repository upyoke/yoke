"""Refuse a landing whose exact candidate nobody has cleared.

The merge boundary runs on the machine that holds the repository; the
clearance lives in the control plane. So the boundary asks the registered
``merge_review.candidate.evaluate`` function about the one commit it is
about to land, and lets that answer decide -- identically over an https
relay and a local Postgres universe, and identically for a project with a
merge queue and one without.

The ask is also what raises the review: an item that needs one and has not
had it gets its request created here, so the refusal a worker reads names
the request a reviewer is already looking at rather than a step somebody
still has to remember to take.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git

EVALUATE_FUNCTION_ID = "merge_review.candidate.evaluate"

#: Answers that mean "this control plane has no candidate review at all",
#: rather than "the review could not be read".
#:
#: A universe learns the posture key and this function in the same deploy:
#: the key is selectable only on a workflow generation whose allowlist
#: carries it, and those generations converge from the build that registers
#: the function. So a control plane that does not serve it provably has no
#: item that can require a review, and proceeding is the rollout order
#: rather than a hole. Treating it as an unreadable answer instead would
#: refuse EVERY merge on EVERY project until the deploy landed -- including
#: the merge that ships the deploy.
_UNSERVED_ERROR_CODES = frozenset(
    {"function_version_skew", "function_not_registered"}
)

_RESOLVE_RECIPE = (
    "`yoke decision-requests resolve {request_id} approve "
    '--note "<what was reviewed>"`'
)


def _short(commit_sha: str) -> str:
    return str(commit_sha or "")[:12]


def _refusal_text(public_ref: str, commit_sha: str, result: dict[str, Any]) -> str:
    """Name what is missing, who supplies it, and what re-runs the merge."""
    request_id = result.get("request_id")
    action = str(result.get("resolution_action") or "")
    head = _short(commit_sha)
    opening = (
        f"{public_ref} selects the merge_candidate_review posture, so the "
        f"exact commit a landing would carry needs a review first, and "
        f"{head} does not have one. Nothing has been merged."
    )
    if action == "reject":
        return (
            f"{public_ref} candidate {head} was reviewed and rejected"
            + (f" (decision request {request_id})" if request_id else "")
            + ". Address the review, commit the fix, and re-run this merge: "
            "the new commit raises its own review."
        )
    if request_id:
        recipe = _RESOLVE_RECIPE.format(request_id=request_id)
        return (
            f"{opening} Decision request {request_id} is open for {head} in "
            f"the reviewer's Inbox; an authorized project owner or operator "
            f"clears it with {recipe}, then re-run this merge. Any commit "
            "made after that clearance needs its own review."
        )
    return (
        f"{opening} Raise the review with `yoke merge-review candidate "
        f"evaluate {public_ref} --commit {commit_sha}`, have it cleared, "
        "then re-run this merge."
    )


def candidate_review_refusal(
    *,
    item_id: int,
    public_ref: str,
    commit_sha: str,
    branch: str,
    target: str,
    repo_root: str,
    dispatch: Callable[..., Any] = call_dispatcher,
) -> str:
    """Why this candidate may not land yet, or empty when it may.

    Fails closed on an unreadable answer: a boundary that cannot ask
    whether a review happened must not answer with a landing.
    """
    response = dispatch(
        function_id=EVALUATE_FUNCTION_ID,
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={
            "commit_sha": str(commit_sha),
            "branch": str(branch),
            "target": str(target),
            "touched_files": list(git.changed_files(repo_root, commit_sha, target)),
        },
    )
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        code = str(getattr(error, "code", "") or "")
        if code in _UNSERVED_ERROR_CODES:
            # Said out loud rather than skipped quietly: an operator reading
            # this merge should see which gate did not run and why.
            print(
                f"[phase:admission] candidate review not served by this "
                f"control plane ({code}); no item here can require one yet, "
                "so the landing proceeds",
                file=sys.stderr,
                flush=True,
            )
            return ""
        detail = getattr(error, "message", None) or "candidate review read failed"
        return (
            f"{public_ref}: candidate review could not be checked: {detail}. "
            "Merge admission asks the control plane whether this exact "
            "commit was cleared; resolve that read and re-run this merge. "
            "Nothing has been merged."
        )
    result = dict(getattr(response, "result", None) or {})
    if not result.get("required") or result.get("satisfied"):
        return ""
    return _refusal_text(public_ref, commit_sha, result)


__all__ = ["EVALUATE_FUNCTION_ID", "candidate_review_refusal"]
