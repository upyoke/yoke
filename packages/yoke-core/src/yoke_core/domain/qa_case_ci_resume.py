"""Keep a candidate on the CI run that already covers it.

The gate rebases the lane before it asks GitHub what has already happened
to the tree. That order is right the first time through: the rebase is what
makes the published candidate the tree the train will build, and nothing is
lost by moving a commit no run has examined.

It is wrong on re-entry. A second invocation over an unchanged lane — the
first was moved to the background by its harness, killed mid-poll, or
re-run from the recovery line the runner itself prints — rebases onto a
base branch that has since advanced. That moves the candidate to a new
commit, so :mod:`yoke_core.domain.qa_case_ci_superseded_run` force-cancels
the still-running run as superseded and the gate pays thirteen minutes for
an answer it was already thirty seconds from receiving.

So the lookup comes first. When a run of this workflow already covers the
lane's current head, that run is this gate's own earlier invocation and the
source candidate is unchanged: the lane stays where it is, and the ordinary
adoption and attachment path downstream resumes the run instead of
replacing it. Queue admission continues on the pull request that run
belongs to. Only an unexamined candidate is rebased, which is the
first-invocation case the rebase exists for, and a changed source or a
genuine integration requirement still reaches the rebase because no run
covers the commit it arrives at.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from yoke_core.domain import (
    qa_case_ci_covering_run,
    qa_case_ci_entry_run,
    qa_case_ci_lane,
    qa_case_ci_progress,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


@dataclass(frozen=True)
class PreparedLane:
    """What the gate should do next about the lane it is verifying.

    ``queue_target`` is the branch the landing pull request opens against,
    or ``None`` for a project on the dispatch path. ``resumed_run`` is the
    run that already covers the candidate, so the caller reuses the lookup
    made here instead of asking GitHub the same question again; ``None``
    means the lane was rebased and the caller does its own lookup for the
    commit the rebase produced.
    """

    queue_target: Optional[str]
    resumed_run: Optional[qa_case_ci_lane.WorkflowRun] = None


def _covering_run(
    checkout: Path,
    *,
    project: str,
    repo: str,
    workflow: str,
    queue_routed: bool,
    timeout_seconds: int,
    required_inputs: Optional[Mapping[str, str]] = None,
) -> Optional[qa_case_ci_lane.WorkflowRun]:
    """The run already answering for the lane's current head, if any.

    The event filter mirrors the one the caller's own downstream lookup
    applies, so a run resumed here is the same run that path then finds. A
    queue-routed gate can only be satisfied by the landing pull request's
    entry run, so resuming a dispatch run there would strand the gate
    waiting for an entry run that never appears.
    """
    head_sha = qa_case_ci_lane.ref_sha(checkout, "HEAD")
    if not head_sha:
        return None
    with qa_case_ci_lane.github_actions_authority():
        run = qa_case_ci_covering_run.find_run_for_tree(
            project=project,
            repo=repo,
            workflow=workflow,
            head_sha=head_sha,
            timeout_seconds=timeout_seconds,
            event="pull_request" if queue_routed else "",
        )
    source = qa_case_ci_covering_run.classify(
        run, head_sha=head_sha, required_inputs=required_inputs,
    )
    if source == qa_case_ci_covering_run.DISPATCHED:
        return None
    return run


def prepare_lane_preserving_covering_run(
    checkout: Path,
    *,
    project: str,
    repo: str,
    workflow: str,
    branch: str,
    lane_is_checked_out: bool,
    requirement_id: int,
    timeout_seconds: int,
    required_inputs: Optional[Mapping[str, str]] = None,
) -> PreparedLane:
    """Rebase the lane, unless a run already covers the candidate it is on.

    The queue target is the same answer
    :func:`yoke_core.domain.qa_case_ci_entry_run.prepare_ci_lane` gives, so
    queue admission continues identically either way: the landing pull
    request the resumed run belongs to is the one the caller converges on.

    A lookup that cannot reach GitHub is named on the progress stream and
    falls through to the rebase, where the identical lookup runs inside the
    caller's recording block and fails there with a QA run recorded against
    the requirement. Refusing here instead would turn a transient read into
    an unrecorded gate failure.
    """
    if lane_is_checked_out:
        queue_routed = qa_case_ci_entry_run.routes_through_merge_queue(project)
        try:
            resumed = _covering_run(
                checkout,
                project=project,
                repo=repo,
                workflow=workflow,
                queue_routed=queue_routed,
                timeout_seconds=timeout_seconds,
                required_inputs=required_inputs,
            )
        except QaCaseExecutionError as exc:
            qa_case_ci_progress.announce_resume_probe_failed(
                requirement_id, detail=str(exc),
            )
            resumed = None
        if resumed is not None:
            qa_case_ci_progress.announce_resumed_candidate(
                requirement_id,
                repo=repo,
                branch=branch,
                head_sha=resumed.head_sha,
                run_id=resumed.run_id,
            )
            return PreparedLane(
                queue_target=(
                    qa_case_ci_entry_run.base_branch(project, checkout)
                    if queue_routed
                    else None
                ),
                resumed_run=resumed,
            )
    return PreparedLane(
        queue_target=qa_case_ci_entry_run.prepare_ci_lane(
            checkout,
            project=project,
            branch=branch,
            lane_is_checked_out=lane_is_checked_out,
        )
    )


__all__ = ["PreparedLane", "prepare_lane_preserving_covering_run"]
