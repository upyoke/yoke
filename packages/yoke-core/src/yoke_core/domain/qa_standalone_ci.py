"""Dispatch manual QA workflows without publishing or rebasing a lane."""

from __future__ import annotations

import json
import time
from pathlib import Path

from yoke_core.domain import qa_case_ci_lane as lane
from yoke_core.domain.qa_case_execution_context import QaCaseExecutionError
from yoke_core.domain.qa_case_execution import (
    required_case_command,
    _execution_checkout,
)
from yoke_core.domain.qa_case_ci_candidate_inputs import case_inputs
from yoke_core.domain.qa_case_budget import (
    resolve_command_case_budget,
    DEFAULT_CI_RUN_TIMEOUT_SECONDS,
)
from yoke_core.domain.qa_case_ci_conclusion import conclusion_from_poll, failure_verdict
from yoke_core.domain.qa_case_ci_empty_diff import _record_run
from yoke_core.domain.verification_tree_binding import TreeIdentity


def standalone_ci_target(
    case: dict, override=None
) -> tuple[Path, str, str, str, str, dict]:
    required_case_command(case)
    workflow = lane.workflow_file(case)
    raw = override or case.get("standalone_checkout_path")
    checkout = Path(raw).resolve() if raw else _execution_checkout(case)
    repo = lane.repo_slug(checkout)
    ref = str(case.get("standalone_source_ref") or "")
    sha = str(case.get("standalone_source_revision") or "")
    if not ref or not sha:
        raise QaCaseExecutionError(
            "standalone_ci_ref_required: pass --expected-branch and --expected-sha for the remote commit"
        )
    remote = lane._git(
        checkout,
        *[
            "ls-remote",
            "origin",
            f"refs/heads/{ref}",
            f"refs/tags/{ref}^{{}}",
            f"refs/tags/{ref}",
        ],
    )
    resolved = {
        line.split()[0] for line in (remote.stdout or "").splitlines() if line.strip()
    }
    if remote.returncode or sha not in resolved:
        raise QaCaseExecutionError(
            f"standalone_ci_commit_mismatch: remote ref {ref!r} does not name {sha}; "
            "name a published branch or tag at the requested commit; this runner never pushes a lane"
        )
    return (
        checkout,
        repo,
        workflow,
        ref,
        sha,
        case_inputs(case, project=str(case["project"])),
    )


def execute_standalone_ci(
    case: dict, *, timeout_seconds=None, checkout_path=None, actor=None
) -> dict:
    checkout, repo, workflow, ref, sha, inputs = standalone_ci_target(
        case, checkout_path
    )
    budget = resolve_command_case_budget(
        case["method_config"],
        explicit_override=timeout_seconds,
        runner_default=DEFAULT_CI_RUN_TIMEOUT_SECONDS,
    )
    started = time.monotonic()
    ci_run_id = ""
    project = str(case["project"])
    evidence = {
        "repo": repo,
        "workflow": workflow,
        "branch": ref,
        "ci_workflow_inputs": inputs,
        "ci_run_source": "dispatched",
        "verification_tree": TreeIdentity(str(checkout), sha).as_payload(),
        **budget.as_record(),
    }
    try:
        with lane.github_actions_authority():
            ci_run_id = lane.dispatch_workflow(
                project=project,
                repo=repo,
                workflow=workflow,
                branch=ref,
                request_id=f"qa-standalone:{case['requirement_id']}:{sha}",
                timeout_seconds=budget.seconds,
                inputs=inputs,
            )
            actual = lane.run_head_sha(project=project, repo=repo, run_id=ci_run_id)
            evidence["observed_ci_head_sha"] = actual
            if actual != sha:
                raise QaCaseExecutionError(
                    f"standalone_ci_run_commit_mismatch: run {ci_run_id} checked out {actual!r}, expected {sha}; "
                    "pin an immutable remote tag at the commit and rerun the plan"
                )
            exit_code, output = lane.await_workflow(
                project=project,
                repo=repo,
                run_id=ci_run_id,
                timeout_seconds=budget.seconds,
            )
        conclusion = conclusion_from_poll(exit_code, output)
        verdict, failure_class = (
            ("pass", "") if conclusion == "success" else failure_verdict(conclusion)
        )
    except Exception as exc:
        output, exit_code, conclusion, verdict, failure_class = (
            str(exc),
            2,
            "error",
            "error",
            "infrastructure_transient",
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    outcome = {
        "ci_run_id": ci_run_id or None,
        "ci_conclusion": conclusion,
        "run_url": f"https://github.com/{repo}/actions/runs/{ci_run_id}"
        if ci_run_id
        else None,
        "exit_code": exit_code,
        "failure_class": failure_class or None,
    }
    run_id, artifact_id = _record_run(
        case,
        raw_result=json.dumps({**evidence, **outcome}, sort_keys=True),
        duration_ms=duration_ms,
        verdict=verdict,
        output=output,
        actor=actor,
    )
    return {
        "requirement_id": int(case["requirement_id"]),
        "run_id": run_id,
        "artifact_id": artifact_id,
        "runner_id": "ci_run",
        "verdict": verdict,
        "case_outcome": "passed"
        if verdict == "pass"
        else "failed"
        if verdict == "fail"
        else "error",
        "duration_ms": duration_ms,
        **evidence,
        **outcome,
    }
