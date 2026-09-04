"""Replace one CI run that remained pending without creating any jobs.

This is also where the gate starts waiting, so it is where the wait is
recorded: the process polling the run dies with the turn that started it,
and the recorded wait is what lets the control-plane sweep deliver the
verdict afterwards. A replacement supersedes the run it replaces, so a
recovery leaves the session owed one verdict rather than two.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_core.domain import (
    qa_case_ci_covering_run,
    qa_case_ci_lane,
    qa_case_ci_progress,
    qa_case_ci_superseded_run,
)
from yoke_core.domain.github_actions_run_stall import (
    CI_RUN_NEVER_STARTED_REASON,
)


@dataclass(frozen=True)
class AwaitedWorkflowRun:
    """The final run identity and poll result after bounded recovery."""

    run_id: str
    run_url: str
    source: str
    exit_code: int
    output: str


def _never_started(output: str) -> bool:
    return CI_RUN_NEVER_STARTED_REASON in str(output or "")


def _joined_output(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


def _record_wait(
    requirement_id: int,
    *,
    repo: str,
    run_id: str,
    head_sha: str,
    supersedes_run_id: str = "",
) -> None:
    """Make this run's verdict reachable if the turn awaiting it ends."""
    from yoke_core.domain.session_ci_wait_record import record_ci_run_wait
    from yoke_core.domain.session_ci_wait_schema import CI_WAIT_QA_CASE

    warning = record_ci_run_wait(
        repo=repo,
        run_id=run_id,
        kind=CI_WAIT_QA_CASE,
        head_sha=head_sha,
        continue_command=f"yoke qa case run --requirement-id {requirement_id}",
        supersedes_run_id=supersedes_run_id,
    )
    if warning:
        qa_case_ci_progress.announce_wait_not_recorded(requirement_id, warning)


def await_with_one_redispatch(
    *,
    requirement_id: int,
    project: str,
    repo: str,
    workflow: str,
    branch: str,
    head_sha: str,
    run_id: str,
    run_url: str,
    source: str,
    timeout_seconds: int,
) -> AwaitedWorkflowRun:
    """Await *run_id*, replacing it once when GitHub never creates jobs."""
    _record_wait(requirement_id, repo=repo, run_id=run_id, head_sha=head_sha)
    exit_code, output = qa_case_ci_lane.await_workflow(
        project=project,
        repo=repo,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
    )
    if not _never_started(output):
        return AwaitedWorkflowRun(
            run_id,
            run_url,
            source,
            exit_code,
            output,
        )

    qa_case_ci_superseded_run.force_cancel_run(
        project=project,
        repo=repo,
        run_id=run_id,
    )
    qa_case_ci_progress.announce_never_started_retry(
        requirement_id,
        repo=repo,
        run_id=run_id,
    )
    replacement_id = qa_case_ci_lane.dispatch_workflow(
        project=project,
        repo=repo,
        workflow=workflow,
        branch=branch,
        request_id=(f"qa-case:{requirement_id}:{head_sha}:never-started-retry"),
        timeout_seconds=timeout_seconds,
    )
    replacement_url = qa_case_ci_progress.announce_run(
        requirement_id,
        repo=repo,
        run_id=replacement_id,
        source=qa_case_ci_covering_run.DISPATCHED,
    )
    _record_wait(
        requirement_id,
        repo=repo,
        run_id=replacement_id,
        head_sha=head_sha,
        supersedes_run_id=run_id,
    )
    replacement_code, replacement_output = qa_case_ci_lane.await_workflow(
        project=project,
        repo=repo,
        run_id=replacement_id,
        timeout_seconds=timeout_seconds,
    )
    if not _never_started(replacement_output):
        return AwaitedWorkflowRun(
            replacement_id,
            replacement_url,
            qa_case_ci_covering_run.DISPATCHED,
            replacement_code,
            _joined_output(output, replacement_output),
        )

    qa_case_ci_superseded_run.force_cancel_run(
        project=project,
        repo=repo,
        run_id=replacement_id,
    )
    failure = qa_case_ci_progress.announce_never_started_terminal(
        requirement_id,
        repo=repo,
        branch=branch,
        run_id=replacement_id,
    )
    return AwaitedWorkflowRun(
        replacement_id,
        replacement_url,
        qa_case_ci_covering_run.DISPATCHED,
        1,
        _joined_output(output, replacement_output, failure),
    )


__all__ = ["AwaitedWorkflowRun", "await_with_one_redispatch"]
