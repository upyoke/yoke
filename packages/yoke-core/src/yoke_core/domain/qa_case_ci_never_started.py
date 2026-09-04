"""Replace one CI run that remained pending without creating any jobs."""

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
