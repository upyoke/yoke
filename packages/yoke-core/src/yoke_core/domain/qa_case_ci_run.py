"""Run a Command-method QA case on the project's CI workflow.

The blocking verification gate for an item is the same suite CI already
runs on every pull request and every push to the integration branch. On a
developer machine that suite competes with every other session for one
machine-wide admission slot and one CPU complement; on CI it fans out
across duration-balanced shards with disposable databases and freshly
provisioned capacity. This executor moves the gate there: push the lane
branch, dispatch the project's declared workflow against it with a
correlation id, wait for the run, and record the run's conclusion as the
case verdict. The lane and workflow plumbing lives in
:mod:`yoke_core.domain.qa_case_ci_lane`.

Recorded evidence names the run URL and the exact head sha the run
covered, so a green is attributable to one tree exactly as a local
``worktree_run`` verdict is (see
:mod:`yoke_core.domain.verification_tree_binding`).

``worktree_run`` remains the local executor for the same Command method
and stays the fallback for offline or local-only operation. Selecting it
is a plan-case choice, never a silent runtime downgrade: when CI cannot
be reached this executor fails with a named reason rather than quietly
running the suite on the machine it exists to keep free.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext

from yoke_core.domain import qa_case_ci_lane, verification_tree_binding
from yoke_core.domain.qa_case_execution import QaCaseExecutionError

#: Executor id recorded on runs this module produces.
EXECUTOR_ID = "ci_run"

#: Wall-clock ceiling for one dispatched CI run. A sharded suite finishes
#: well inside this; the bound exists so a cancelled or never-scheduled
#: run reports a timeout instead of waiting forever. The budget belongs to
#: the CI run, not to the local process timeout a ``worktree_run`` case
#: would apply to its own command.
DEFAULT_CI_RUN_TIMEOUT_SECONDS = 5400

#: Surface name carried by this executor's tree-binding refusal.
_TREE_BINDING_SURFACE = "qa case run (ci)"


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
            "executor_type": EXECUTOR_ID,
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


def _resolve_checkout(case: dict, checkout_path: Optional[str | Path]) -> Path:
    from yoke_core.domain.qa_case_execution import _execution_checkout

    checkout = (
        Path(checkout_path).resolve()
        if checkout_path is not None
        else _execution_checkout(case)
    )
    if not checkout.is_dir():
        raise QaCaseExecutionError(f"CI execution checkout does not exist: {checkout}")
    binding = verification_tree_binding.evaluate_run(
        surface=_TREE_BINDING_SURFACE, tree=str(checkout),
    )
    if binding.notice:
        print(binding.notice, file=sys.stderr, flush=True)
    if binding.refusal:
        raise QaCaseExecutionError(binding.refusal)
    return checkout


def execute_ci_case(
    case: dict,
    *,
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    actor: Optional[ActorContext] = None,
) -> dict[str, Any]:
    """Push the lane, run the project's CI workflow, record the verdict."""
    checkout = _resolve_checkout(case, checkout_path)
    configured = case["method_config"].get("timeout_seconds")
    budget = int(
        timeout_seconds
        if timeout_seconds is not None
        else (configured or DEFAULT_CI_RUN_TIMEOUT_SECONDS)
    )
    workflow = qa_case_ci_lane.workflow_file(case)
    project = str(case["project"])
    repo = qa_case_ci_lane.repo_slug(checkout)
    branch = qa_case_ci_lane.lane_branch(case, checkout)
    tree = verification_tree_binding.resolve_tree_identity(checkout)
    head_sha = tree.head_sha if tree else ""
    qa_case_ci_lane.push_lane(checkout, branch)

    started = time.monotonic()
    with qa_case_ci_lane.github_actions_authority():
        ci_run_id = qa_case_ci_lane.dispatch_workflow(
            project=project,
            repo=repo,
            workflow=workflow,
            branch=branch,
            # Keyed on the tree under test: a retry after a lost response
            # recovers the same run, while a new commit is a new gate.
            request_id=f"qa-case:{int(case['requirement_id'])}:{head_sha}",
            timeout_seconds=budget,
        )
        exit_code, poll_output = qa_case_ci_lane.await_workflow(
            project=project, repo=repo, run_id=ci_run_id, timeout_seconds=budget,
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    verdict = "pass" if exit_code == 0 else "fail"
    run_url = f"https://github.com/{repo}/actions/runs/{ci_run_id}"
    raw_result = json.dumps(
        {
            "repo": repo,
            "workflow": workflow,
            "branch": branch,
            "ci_run_id": ci_run_id,
            "run_url": run_url,
            "exit_code": exit_code,
            "verification_tree": tree.as_payload() if tree else None,
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
        "requirement_id": int(case["requirement_id"]),
        "run_id": qa_run_id,
        "artifact_id": artifact_id,
        "executor_id": EXECUTOR_ID,
        "verdict": verdict,
        "case_outcome": "passed" if verdict == "pass" else "failed",
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "ci_run_id": ci_run_id,
        "run_url": run_url,
        "verification_tree": tree.as_payload() if tree else None,
    }


__all__ = [
    "DEFAULT_CI_RUN_TIMEOUT_SECONDS",
    "EXECUTOR_ID",
    "execute_ci_case",
]
