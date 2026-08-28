"""Which existing run already answers for the tree under test.

A gate run is 13-14 minutes of shared CI capacity, and GitHub already
holds a durable record of every run keyed by workflow and commit. So
before the gate dispatches anything it asks that record what has already
happened to the tree in front of it: a concluded run on the exact commit
is *adopted* as the verdict, a run still in flight there is *attached* to
and polled, and only an unexamined tree is *dispatched*.

Exactness is the whole safety argument. The lookup filters on the head
SHA server-side and this module checks it again, because a run on any
other commit checked out a different tree and can never stand in for this
one.

Adoption is also the recovery when a gate invocation dies mid-poll: the
local process is gone but its run is not, so the next invocation finds
the concluded run and records its verdict instead of paying for the same
answer twice. Attachment is the same insight one step earlier — a second
invocation while the first run is still going joins it rather than
racing a duplicate.
"""

from __future__ import annotations

import json
from typing import Optional

from yoke_core.domain.qa_case_ci_conclusion import BINDING_CONCLUSIONS
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_case_ci_lane import WorkflowRun

#: This invocation dispatched the run and polled it to a conclusion.
DISPATCHED = "dispatched"
#: The run had already concluded when this invocation looked, so no CI
#: work happened here at all — the verdict is that run's conclusion.
ADOPTED = "adopted"
#: The run was already in flight; this invocation polled that run to its
#: conclusion rather than dispatching a second one on the same commit.
ATTACHED = "attached"
#: No CI run backs this verdict, which is what an empty-diff lane means:
#: there is nothing for CI to be applicable to.
NOT_EXECUTED = "not_executed"

#: Every value :func:`classify` and the runners may record.
SOURCES = frozenset({DISPATCHED, ADOPTED, ATTACHED, NOT_EXECUTED})


def find_run_for_tree(
    *,
    project: str,
    repo: str,
    workflow: str,
    head_sha: str,
    timeout_seconds: int,
    event: str = "",
    status: str = "",
) -> Optional[WorkflowRun]:
    """Return the newest run of *workflow* on exactly *head_sha*, if any.

    ``event`` narrows the lookup to runs GitHub triggered that way, which
    is what a merge-queue project needs: only the landing pull request's
    own entry run can satisfy that project's required check. Leaving it
    empty asks about the commit rather than about how a run started,
    which is what the dispatch path wants — a run it dispatched earlier
    and lost is evidence about this tree however it was triggered.

    ``status`` narrows to runs in that state; empty asks for the newest
    run whatever it is doing, so an in-flight run is visible to attach to
    instead of being duplicated.
    """
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions

    args = []
    for flag, value in (("--event", event), ("--status", status)):
        if value:
            args.extend((flag, value))
    result = _github_actions(
        "find-run", repo, workflow, head_sha, *args, "--json",
        project=project, sd=None, timeout=timeout_seconds,
    )
    try:
        response = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise _lookup_failed(workflow, repo, head_sha, result) from exc
    payload = response.get("result") if isinstance(response, dict) else None
    # Exit 1 with a well-formed "not found" is the adapter's answer for an
    # untested commit, not a transport failure.
    if result.returncode == 1 and isinstance(payload, dict):
        if not payload.get("found"):
            return None
    if result.returncode != 0 or not isinstance(payload, dict):
        raise _lookup_failed(workflow, repo, head_sha, result)
    if not payload.get("found"):
        return None
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise QaCaseExecutionError(
            f"workflow run lookup for {workflow} on {repo}@{head_sha[:12]} "
            "reported a run with no run id"
        )
    return WorkflowRun(
        run_id=run_id,
        status=str(payload.get("status") or "").strip(),
        conclusion=str(payload.get("conclusion") or "").strip(),
        html_url=str(payload.get("html_url") or "").strip(),
        head_sha=str(payload.get("head_sha") or "").strip(),
    )


def _lookup_failed(
    workflow: str, repo: str, head_sha: str, result,
) -> QaCaseExecutionError:
    detail = (result.stderr or result.stdout or "").strip()
    return QaCaseExecutionError(
        f"could not query workflow runs for {workflow} on "
        f"{repo}@{head_sha[:12]}: {detail or 'lookup failed'}"
    )


def classify(run: Optional[WorkflowRun], *, head_sha: str) -> str:
    """Name what *run* lets this invocation do about *head_sha*.

    A run on any other commit, or none at all, means this tree is
    unexamined and has to be dispatched. A completed run that reached a
    verdict about the tree is adopted; one that stopped without reaching
    one is not, because adopting it would wedge the gate at this commit —
    every retry would find the same cancelled run and no green would be
    reachable short of a new commit. Anything still running is attached
    to, which is the same evidence a moment earlier.
    """
    if run is None or not run.head_sha or run.head_sha != head_sha:
        return DISPATCHED
    if run.status == "completed":
        return ADOPTED if run.conclusion in BINDING_CONCLUSIONS else DISPATCHED
    return ATTACHED


__all__ = [
    "ADOPTED",
    "ATTACHED",
    "DISPATCHED",
    "NOT_EXECUTED",
    "SOURCES",
    "classify",
    "find_run_for_tree",
]
