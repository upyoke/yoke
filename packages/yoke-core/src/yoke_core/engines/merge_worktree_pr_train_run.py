"""The ``merge_group`` workflow run that validates one train's combined head.

Separate from :mod:`yoke_core.engines.merge_worktree_pr_queue`, which owns
the pull request's own queue entry and arming. This module answers a
different question — what GitHub Actions ran for the train the pull request
was folded into — and reads Actions rather than pull requests to answer it.

The lookup is anchored, never recent. A member that parks across a release
wait reaches close-out hours and dozens of trains after its own run, so a
fixed page of the newest ``merge_group`` runs cannot reach it: the run is
still green and still there, and only the reader's window has moved on.
Two things keep the reach honest. The request goes to the declared
workflow's own runs collection, so a second ``merge_group`` workflow in the
same repository no longer halves the depth. And a known combined head is
asked for by ``head_sha``, which is an index rather than a window — the age
of the run stops mattering at all. Only a lookup with no combined head to
anchor on pages, and it says how far it reached when it finds nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS as ACTIONS_READ,
)

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.domain.project_ci_workflow import project_ci_workflow_file
from yoke_core.engines.merge_worktree_pr_queue import resolve_auth_detail
from yoke_core.engines.merge_worktree_prepare import MergeContext


# Every branch the queue builds a train on is named under this prefix.
# GitHub names the ref after one member (``pr-<number>-``); the rest of
# a batch share that train's combined-head SHA, not that marker.
_QUEUE_REF_PREFIX = "gh-readonly-queue/"

# Marker paging is the unanchored path, so it is the only one that needs a
# stop. At the maximum page size this reaches back a few hundred trains,
# well past any release wait, while still terminating on a repository whose
# queue history is arbitrarily long.
_RUNS_PAGE_SIZE = 100
_RUNS_PAGE_LIMIT = 5


@dataclass(frozen=True)
class TrainRun:
    """The ``merge_group`` workflow run validating one train's combined head."""

    status: str = ""
    conclusion: str = ""
    head_sha: str = ""
    url: str = ""


@dataclass(frozen=True)
class TrainRunLookupFailure:
    """Why no run was identified, and whether asking again could change it.

    ``retryable`` is the fact a caller needs and cannot infer from the text.
    A provider that refused the read may answer the same question next
    minute; an anchored search that completed and found nothing will return
    the identical answer forever, and telling an owner to re-run it is how a
    close-out sends someone around a loop that has no exit.
    """

    reason: str
    recovery: str
    retryable: bool

    def __str__(self) -> str:
        return f"{self.reason}. {self.recovery}" if self.recovery else self.reason


def _as_train_run(run: Mapping[str, Any]) -> TrainRun:
    return TrainRun(
        status=str(run.get("status") or ""),
        conclusion=str(run.get("conclusion") or ""),
        head_sha=str(run.get("head_sha") or ""),
        url=str(run.get("html_url") or ""),
    )


def _runs_page(
    *,
    owner: str,
    repo: str,
    workflow: str,
    token: str,
    query: Mapping[str, str],
) -> tuple[list[Mapping[str, Any]], Optional[TrainRunLookupFailure]]:
    """One page of the declared workflow's ``merge_group`` runs.

    Scoping the request to the workflow's own collection is what keeps a
    second ``merge_group`` workflow — a CLA check, a label sync — from
    spending the page budget on runs this reader would only discard.
    """
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=(
                    f"/repos/{owner}/{repo}/actions/workflows/{workflow}/runs"
                ),
                query=dict(query),
            ),
            token=token,
        )
    except RestTransportError as exc:
        return [], TrainRunLookupFailure(
            reason=f"merge_group run lookup failed: {exc}",
            recovery=(
                "The provider read failed rather than answering; re-run the "
                "same close-out command once it is reachable."
            ),
            retryable=True,
        )
    body = response.body if isinstance(response.body, dict) else {}
    runs = [
        run for run in (body.get("workflow_runs") or []) if isinstance(run, dict)
    ]
    return runs, None


def read_train_run(
    ctx: MergeContext, pr_num: str, *, covering_sha: str = ""
) -> tuple[Optional[TrainRun], Optional[TrainRunLookupFailure]]:
    """The merge_group run covering ``pr_num``'s train.

    Identified by the project's declared CI workflow plus either an exact
    combined-head SHA match (``covering_sha``, typically this pull request's
    merge commit) or the queue ref's ``pr-<number>-`` marker. Returns
    ``(None, reason)`` rather than substituting another workflow or a run
    whose head is a different revision.
    """
    auth, auth_err = resolve_auth_detail(ctx, ACTIONS_READ)
    if auth_err or auth is None:
        return None, TrainRunLookupFailure(
            reason=f"merge_group run lookup unavailable: {auth_err}",
            recovery=(
                "Restore the project's GitHub binding for Actions reads, then "
                "re-run the same close-out command."
            ),
            retryable=True,
        )
    owner, repo = split_repo(auth.repo)
    try:
        workflow = project_ci_workflow_file(str(ctx.project or ""))
    except RuntimeError as exc:
        return None, TrainRunLookupFailure(
            reason=f"merge_group workflow identity lookup failed: {exc}",
            recovery=(
                "Repair the project's declared CI workflow file, then re-run "
                "the same close-out command."
            ),
            retryable=True,
        )
    if not workflow:
        return None, TrainRunLookupFailure(
            reason="merge_group workflow identity is not declared",
            recovery=(
                "Declare the project's ci_workflow_file; until then no "
                "merge-group run can be attributed to this landing."
            ),
            retryable=False,
        )
    workflow_path = f".github/workflows/{workflow}"
    covering = covering_sha.strip()

    if covering:
        # ``head_sha`` is an index on the runs collection, so this reaches a
        # train from any distance. It is asked first because it is the exact
        # question: this pull request's merge commit IS the combined head the
        # queue validated.
        runs, error = _runs_page(
            owner=owner,
            repo=repo,
            workflow=workflow,
            token=auth.token,
            query={
                "event": "merge_group",
                "head_sha": covering,
                "per_page": str(_RUNS_PAGE_SIZE),
            },
        )
        if error:
            return None, error
        for run in runs:
            if str(run.get("path") or "") != workflow_path:
                continue
            if str(run.get("head_sha") or "") == covering:
                return _as_train_run(run), None

    marker = f"pr-{pr_num}-"
    pages_read = 0
    for page in range(1, _RUNS_PAGE_LIMIT + 1):
        runs, error = _runs_page(
            owner=owner,
            repo=repo,
            workflow=workflow,
            token=auth.token,
            query={
                "event": "merge_group",
                "per_page": str(_RUNS_PAGE_SIZE),
                "page": str(page),
            },
        )
        if error:
            return None, error
        pages_read += 1
        for run in runs:
            if str(run.get("path") or "") != workflow_path:
                continue
            head_branch = str(run.get("head_branch") or "")
            if not head_branch.startswith(_QUEUE_REF_PREFIX):
                continue
            head_sha = str(run.get("head_sha") or "")
            if marker in head_branch or (covering and head_sha == covering):
                return _as_train_run(run), None
        if len(runs) < _RUNS_PAGE_SIZE:
            break

    covering_clause = (
        f", and no {workflow!r} run has head {covering}" if covering else ""
    )
    return None, TrainRunLookupFailure(
        reason=(
            f"no merge_group workflow run identified for pull request "
            f"{pr_num}: no {workflow!r} queue ref carries the marker "
            f"{marker!r} within the {pages_read * _RUNS_PAGE_SIZE} most "
            f"recent merge_group runs of that workflow{covering_clause}"
        ),
        recovery=(
            "This search was anchored, so re-running it returns the same "
            f"answer: the train that landed pull request {pr_num} has no run "
            f"of {workflow!r} to attribute. Confirm the queue ran that "
            "workflow on the merge group; if it genuinely did not, the "
            "landing has no merge-group proof to record and the item needs "
            "an operator decision rather than another close-out attempt."
        ),
        retryable=False,
    )


__all__ = ["TrainRun", "TrainRunLookupFailure", "read_train_run"]
