"""Run a Command-method QA case on the project's CI workflow.

The blocking verification gate for an item is the same suite CI already
runs on every pull request and every push to the integration branch. On a
developer machine that suite competes with every other session for one
machine-wide admission slot and one CPU complement; on CI it fans out
across duration-balanced shards with disposable databases and freshly
provisioned capacity. This runner moves the gate there: push the lane,
reuse a pull-request run that reached a verdict on its exact commit when
one exists, otherwise dispatch the project's declared workflow, and record
the run's conclusion as the case verdict. The lane and workflow plumbing
lives in :mod:`yoke_core.domain.qa_case_ci_lane`, and what a conclusion
makes a run in :mod:`yoke_core.domain.qa_case_ci_conclusion`.

A project landing through the merge queue reaches that reuse path by
construction rather than by luck: it rebases and opens its landing pull
request here, so the entry run GitHub mints *is* the gate run
(:mod:`yoke_core.domain.qa_case_ci_entry_run`). Dispatch stays the fallback
for every other project, and for a queue project whose pull request
produced no run.

Recorded evidence names the run URL and the exact head sha the run
covered, so a green is attributable to one tree exactly as a local
``worktree_run`` verdict is (see
:mod:`yoke_core.domain.verification_tree_binding`).

``worktree_run`` remains the local runner for the same Command method
and stays the fallback for offline or local-only operation. Selecting it
is a plan-case choice, never a silent runtime downgrade: when CI cannot
be reached this runner fails with a named reason rather than quietly
running the suite on the machine it exists to keep free.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext

from yoke_core.domain import (
    qa_case_budget,
    qa_case_ci_entry_run,
    qa_case_ci_lane,
    qa_case_ci_progress,
    verification_tree_binding,
)
from yoke_core.domain.qa_case_ci_conclusion import (
    BINDING_CONCLUSIONS,
    conclusion_from_poll,
    failure_verdict,
)
from yoke_core.domain.qa_case_execution import (
    QaCaseExecutionError,
    required_case_command,
)

#: Runner id recorded on runs this module produces.
EXECUTOR_ID = "ci_run"

#: Wall-clock ceiling for one dispatched CI run. A sharded suite finishes
#: well inside this; the bound exists so a cancelled or never-scheduled
#: run reports a timeout instead of waiting forever. The budget belongs to
#: the CI run, not to the local process timeout a ``worktree_run`` case
#: would apply to its own command.
DEFAULT_CI_RUN_TIMEOUT_SECONDS = qa_case_budget.DEFAULT_CI_RUN_TIMEOUT_SECONDS


def _record_run(
    case: dict,
    *,
    raw_result: str,
    duration_ms: int,
    verdict: str,
    output: str,
    actor: Optional[ActorContext],
) -> tuple[int, int]:
    from yoke_core.domain.qa_artifact_handle import local_handle
    from yoke_core.domain.qa_artifacts import (
        artifact_file_path,
        case_artifact_subject,
    )
    from yoke_core.domain.qa_case_execution import recording_leg

    call_qa = recording_leg(case, actor=actor)
    run = call_qa(
        "qa.run.add",
        {
            "performed_by": EXECUTOR_ID,
            "raw_result": raw_result,
            "duration_ms": duration_ms,
        },
    )
    run_id = int(run["qa_run_id"])
    output_path = artifact_file_path(
        str(case["project"]),
        case_artifact_subject(case),
        run_id,
        "ci-run-output.txt",
    )
    output_path.write_text(output, encoding="utf-8")
    artifact = call_qa(
        "qa.artifact.add",
        {
            "run_id": run_id,
            "artifact_type": "command_output",
            "content_type": "text/plain",
            "artifact_handle": local_handle(
                str(output_path.resolve()), "text/plain",
            ),
            "metadata": json.dumps(
                {"case_key": case["case_key"], "verdict": verdict},
                sort_keys=True,
            ),
        },
    )
    call_qa(
        "qa.run.complete",
        {
            "run_id": run_id,
            "verdict": verdict,
            "raw_result": raw_result,
            "duration_ms": duration_ms,
        },
    )
    return run_id, int(artifact["qa_artifact_id"])


def _resolve_checkout(
    case: dict,
    checkout_path: Optional[str | Path],
    *,
    allow_tree_mismatch: bool = False,
) -> Path:
    from yoke_core.domain.qa_case_execution import _execution_checkout

    checkout = (
        Path(checkout_path).resolve()
        if checkout_path is not None
        else _execution_checkout(case)
    )
    if not checkout.is_dir():
        raise QaCaseExecutionError(f"CI execution checkout does not exist: {checkout}")
    # CI verifies a pushed commit on a remote runner. The checkout is only a
    # Git transport, so local claim-tree binding does not apply to this
    # runner; the recorded source SHA is the binding authority instead.
    return checkout


def execute_ci_case(
    case: dict,
    *,
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    allow_tree_mismatch: bool = False,
    actor: Optional[ActorContext] = None,
) -> dict[str, Any]:
    """Push the lane, reuse or run its CI workflow, and record the verdict."""
    # Both halves of the contract are judged before anything moves: a case
    # with no command or no workflow has no runnable path, and saying so
    # here costs nothing, while saying it after the lane is pushed leaves a
    # published branch behind an exit that recorded no verdict.
    required_case_command(case)
    workflow = qa_case_ci_lane.workflow_file(case)
    checkout = _resolve_checkout(
        case, checkout_path, allow_tree_mismatch=allow_tree_mismatch,
    )
    selected_budget = qa_case_budget.resolve_command_case_budget(
        case["method_config"],
        explicit_override=timeout_seconds,
        runner_default=DEFAULT_CI_RUN_TIMEOUT_SECONDS,
    )
    budget = selected_budget.seconds
    started = time.monotonic()
    requirement_id = int(case["requirement_id"])
    project = str(case["project"])
    repo = qa_case_ci_lane.repo_slug(checkout)
    branch = qa_case_ci_lane.lane_branch(case, checkout)
    try:
        checked_out_branch = qa_case_ci_lane.checked_out_branch(checkout)
    except QaCaseExecutionError:
        checked_out_branch = ""
    # Rebase before the head sha is resolved: the rebase is what it names.
    entry_run_base = qa_case_ci_entry_run.prepare_entry_run_lane(
        checkout, project=project, branch=branch,
        lane_is_checked_out=checked_out_branch == branch,
    )
    tree = verification_tree_binding.resolve_tree_identity(checkout)
    if not checked_out_branch:
        checked_out_branch = branch if tree else "HEAD"
    source_ref = (
        "HEAD" if checked_out_branch == branch
        else str(case.get("lane_commit_sha") or "").strip()
    )
    if not source_ref:
        raise QaCaseExecutionError(
            f"CI case for {branch!r} has no recorded commit after lane cleanup"
        )
    head_sha = (
        tree.head_sha if source_ref == "HEAD" and tree is not None
        else qa_case_ci_lane.ref_sha(checkout, source_ref)
    )
    tree = verification_tree_binding.TreeIdentity(str(checkout), head_sha)
    ci_run_id = ""
    run_url = ""
    reused_pull_request_run = False
    known_conclusion = ""
    try:
        qa_case_ci_lane.push_lane(checkout, branch, source_ref=source_ref)
        with qa_case_ci_lane.github_actions_authority():
            if entry_run_base is not None:
                qa_case_ci_entry_run.open_landing_pull_request(
                    checkout, project=project, branch=branch,
                    target=entry_run_base, lane_head=head_sha,
                )
                covering_run = qa_case_ci_entry_run.await_entry_run(
                    requirement_id=requirement_id,
                    project=project, repo=repo, workflow=workflow,
                    head_sha=head_sha, timeout_seconds=budget,
                )
            else:
                covering_run = qa_case_ci_lane.find_pull_request_run(
                    project=project, repo=repo, workflow=workflow,
                    head_sha=head_sha, timeout_seconds=budget,
                )
            if (
                covering_run is not None
                and covering_run.status == "completed"
                and covering_run.head_sha == head_sha
                and covering_run.conclusion in BINDING_CONCLUSIONS
            ):
                reused_pull_request_run = True
                ci_run_id = covering_run.run_id
                run_url = covering_run.html_url
                known_conclusion = covering_run.conclusion
                if entry_run_base is None:
                    qa_case_ci_progress.announce_run(
                        requirement_id, repo=repo, run_id=ci_run_id,
                        html_url=run_url, source="covering",
                    )
                exit_code = 0 if known_conclusion == "success" else 1
                poll_output = f"reused pull_request run: {known_conclusion}"
            else:
                qa_case_ci_progress.announce_dispatch(
                    requirement_id, repo=repo, workflow=workflow,
                    branch=branch,
                )
                ci_run_id = qa_case_ci_lane.dispatch_workflow(
                    project=project, repo=repo, workflow=workflow, branch=branch,
                    request_id=f"qa-case:{requirement_id}:{head_sha}",
                    timeout_seconds=budget,
                )
                run_url = qa_case_ci_progress.announce_run(
                    requirement_id, repo=repo, run_id=ci_run_id,
                    source="dispatched",
                )
                exit_code, poll_output = qa_case_ci_lane.await_workflow(
                    project=project, repo=repo, run_id=ci_run_id,
                    timeout_seconds=budget,
                )
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        raw_result = json.dumps(
            {
                "repo": repo,
                "workflow": workflow,
                "branch": branch,
                "ci_run_id": ci_run_id or None,
                "ci_conclusion": "error",
                "failure_class": "infrastructure_transient",
                "error": str(exc),
                "verification_tree": tree.as_payload(),
                **selected_budget.as_record(),
            },
            sort_keys=True,
        )
        run_id, _ = _record_run(
            case, raw_result=raw_result, duration_ms=duration_ms,
            verdict="error", output=str(exc), actor=actor,
        )
        raise QaCaseExecutionError(
            f"CI execution errored; recorded QA run #{run_id}: {exc}"
        ) from exc
    duration_ms = int((time.monotonic() - started) * 1000)
    conclusion = known_conclusion or conclusion_from_poll(exit_code, poll_output)
    verdict, failure_class = (
        ("pass", "") if conclusion == "success"
        else failure_verdict(conclusion)
    )
    run_url = run_url or f"https://github.com/{repo}/actions/runs/{ci_run_id}"
    raw_result = json.dumps(
        {
            "repo": repo,
            "workflow": workflow,
            "branch": branch,
            "ci_run_id": ci_run_id,
            "run_url": run_url,
            "exit_code": exit_code,
            "ci_conclusion": conclusion,
            "reused_pull_request_run": reused_pull_request_run,
            "failure_class": failure_class or None,
            "verification_tree": tree.as_payload(),
            **selected_budget.as_record(),
        },
        sort_keys=True,
    )
    output = (
        f"$ {workflow} on {repo}@{branch} ({head_sha[:12] or 'unknown sha'})\n"
        f"{run_url}\n\n[output]\n{poll_output}\n\n[exit_code]\n{exit_code}\n"
    )
    qa_run_id, artifact_id = _record_run(
        case,
        raw_result=raw_result,
        duration_ms=duration_ms,
        verdict=verdict,
        output=output,
        actor=actor,
    )
    return {
        "requirement_id": requirement_id,
        "run_id": qa_run_id,
        "artifact_id": artifact_id,
        "runner_id": EXECUTOR_ID,
        "verdict": verdict,
        "case_outcome": (
            "passed" if verdict == "pass" else
            "failed" if verdict == "fail" else "infrastructure_transient"
        ),
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "ci_run_id": ci_run_id,
        "run_url": run_url,
        "ci_conclusion": conclusion,
        "reused_pull_request_run": reused_pull_request_run,
        "failure_class": failure_class or None,
        **selected_budget.as_record(),
        "verification_tree": tree.as_payload(),
    }


__all__ = [
    "DEFAULT_CI_RUN_TIMEOUT_SECONDS",
    "EXECUTOR_ID",
    "execute_ci_case",
]
