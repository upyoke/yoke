"""Empty-diff lanes pass command-ci by inapplicability, with a receipt."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext

from yoke_core.domain import qa_case_ci_lane
from yoke_core.domain.qa_case_budget import CommandCaseBudget
from yoke_core.domain.verification_tree_binding import TreeIdentity

EXECUTOR_ID = "ci_run"


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
                str(output_path.resolve()),
                "text/plain",
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


def lane_has_no_commits_against_target(checkout: Path, target: str) -> bool:
    """True when HEAD introduces nothing beyond *target*.

    A failed comparison is not an empty diff — the existing push/PR path
    stays responsible when git cannot answer.
    """
    if not target:
        return False
    counted = _rev_list_count(checkout, f"origin/{target}..HEAD")
    if counted is None:
        counted = _rev_list_count(checkout, f"{target}..HEAD")
    return counted == 0


def find_covering_run(
    *,
    project: str,
    repo: str,
    workflow: str,
    head_sha: str,
    timeout_seconds: int,
) -> Optional[qa_case_ci_lane.WorkflowRun]:
    """Return any workflow run already recorded for *head_sha*, if any."""
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions

    result = _github_actions(
        "find-run",
        repo,
        workflow,
        head_sha,
        "--json",
        project=project,
        sd=None,
        timeout=timeout_seconds,
    )
    try:
        response = json.loads(result.stdout or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    payload = response.get("result") if isinstance(response, dict) else None
    if not isinstance(payload, dict) or not payload.get("found"):
        return None
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        return None
    return qa_case_ci_lane.WorkflowRun(
        run_id=run_id,
        status=str(payload.get("status") or "").strip(),
        conclusion=str(payload.get("conclusion") or "").strip(),
        html_url=str(payload.get("html_url") or "").strip(),
        head_sha=str(payload.get("head_sha") or head_sha).strip(),
    )


def record_pass_if_empty(
    case: dict,
    checkout: Path,
    *,
    actor: Optional[ActorContext],
    started: float,
    selected_budget: CommandCaseBudget,
    project: str,
    repo: str,
    workflow: str,
    branch: str,
    head_sha: str,
    tree: TreeIdentity,
    target: str,
    requirement_id: int,
    budget: int,
) -> Optional[dict[str, Any]]:
    """Record an inapplicable pass when the lane matches *target*, else None."""
    if not lane_has_no_commits_against_target(checkout, target):
        return None
    covering = _lookup_covering_run(
        project=project,
        repo=repo,
        workflow=workflow,
        head_sha=head_sha,
        timeout_seconds=budget,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    run_url = covering.html_url if covering else ""
    ci_run_id = covering.run_id if covering else ""
    raw_result = json.dumps(
        {
            "repo": repo,
            "workflow": workflow,
            "branch": branch,
            "ci_run_id": ci_run_id or None,
            "run_url": run_url or None,
            "exit_code": 0,
            "ci_conclusion": "success",
            "empty_diff": True,
            "integration_target": target,
            "reused_pull_request_run": False,
            "failure_class": None,
            "verification_tree": tree.as_payload(),
            **selected_budget.as_record(),
        },
        sort_keys=True,
    )
    output = (
        f"$ empty-diff {workflow} on {repo}@{branch} "
        f"({head_sha[:12] or 'unknown sha'}) equals {target}\n"
        f"{run_url}\n\n[output]\ninapplicable: no commits against {target}\n"
        "\n[exit_code]\n0\n"
    )
    qa_run_id, artifact_id = _record_run(
        case,
        raw_result=raw_result,
        duration_ms=duration_ms,
        verdict="pass",
        output=output,
        actor=actor,
    )
    return {
        "requirement_id": requirement_id,
        "run_id": qa_run_id,
        "artifact_id": artifact_id,
        "runner_id": EXECUTOR_ID,
        "verdict": "pass",
        "case_outcome": "passed",
        "exit_code": 0,
        "duration_ms": duration_ms,
        "ci_run_id": ci_run_id,
        "run_url": run_url,
        "ci_conclusion": "success",
        "reused_pull_request_run": False,
        "empty_diff": True,
        "failure_class": None,
        **selected_budget.as_record(),
        "verification_tree": tree.as_payload(),
    }


def _lookup_covering_run(**kwargs) -> Optional[qa_case_ci_lane.WorkflowRun]:
    try:
        with qa_case_ci_lane.github_actions_authority():
            return find_covering_run(**kwargs)
    except Exception:  # noqa: BLE001 — a missed covering run must not fail the pass
        return None


def _rev_list_count(checkout: Path, spec: str) -> Optional[int]:
    result = qa_case_ci_lane._git(checkout, "rev-list", "--count", spec)
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    if not text.isdigit():
        return None
    return int(text)


__all__ = [
    "find_covering_run",
    "lane_has_no_commits_against_target",
    "record_pass_if_empty",
]
