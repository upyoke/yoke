"""Align Yoke deploy records with GitHub Actions truth."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

from yoke_core.domain.deploy_pipeline_reporting import (
    _emit_run_event,
    _flow_db,
    _github_actions,
    _project_db,
    _run_cmd,
    _yoke_db,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_checkout_locations import checkout_for_project


EXIT_OK, EXIT_ERROR, EXIT_RUNNING, EXIT_USAGE = 0, 1, 2, 3

_FAILED_SUFFIX = "-failed"


@dataclass
class ReconcileResult:
    outcome: str
    item_id: int
    deploy_stage: str = ""
    workflow_run_id: str = ""
    gh_status: str = ""
    gh_conclusion: str = ""
    message: str = ""


def _parse_item_id(arg: str) -> int:
    if not arg or not arg.strip():
        raise ValueError("missing item id")
    s = arg.strip().upper()
    if s.startswith("YOK-"):
        s = s[4:]
    s = s.lstrip("0") or "0"
    return int(s)


def _resolve_run_for_item(item_id: int) -> str:
    from yoke_core.domain.deployment_runs_crud_query import cmd_find_by_item

    raw = cmd_find_by_item(item_id)
    if not raw:
        return ""
    first = raw.split("\n", 1)[0].strip()
    return first.split("|", 1)[0] if first else ""


def _resolve_project_and_flow(run_id: str) -> Tuple[str, str]:
    row = _yoke_db("runs", "get", run_id)
    if not row:
        return "", ""
    fields = row.split("|")
    return (fields[1] if len(fields) > 1 else ""), (fields[2] if len(fields) > 2 else "")


def _resolve_workflow_for_stage(flow_id: str, stage_name: str) -> str:
    stages_json = _flow_db("stages", flow_id)
    if not stages_json:
        return ""
    try:
        stages = json.loads(stages_json)
    except (TypeError, ValueError):
        return ""
    for stage in stages:
        if stage.get("name") == stage_name:
            return stage.get("workflow", "") or ""
    return ""


def _resolve_head_sha(project_repo_path: str) -> str:
    if project_repo_path:
        rc = _run_cmd(["git", "-C", project_repo_path, "rev-parse", "HEAD"])
        if rc.returncode == 0:
            sha = (rc.stdout or "").strip()
            if sha:
                return sha
    rc = _run_cmd(["git", "rev-parse", "HEAD"])
    return (rc.stdout or "").strip() if rc.returncode == 0 else ""


def _find_workflow_run(github_repo: str, workflow: str, head_sha: str) -> str:
    r = _github_actions("find-run", github_repo, workflow, head_sha)
    run_id = (r.stdout or "").strip()
    return "" if not run_id or run_id == "not_found" else run_id


def _emit_retroactive_completion(
    *,
    run_id: str,
    stage_name: str,
    workflow_run_id: str,
    member_items: List[str],
    project: str,
) -> None:
    _emit_run_event(
        "DeploymentRunStageCompleted",
        "completed",
        {
            "run_id": run_id,
            "stage": stage_name,
            "result": "success",
            "reconciled": True,
            "workflow_run": workflow_run_id,
            "reason": "usher-reconcile-github",
        },
        member_items=member_items,
        project=project,
    )


def _clear_deploy_stage(item_id: int, stage_name: str) -> str:
    from yoke_core.domain.yoke_function_dispatch import dispatch
    from yoke_contracts.api.function_call import FunctionCallRequest

    session_id = os.environ.get("YOKE_SESSION_ID", "")
    response = dispatch(FunctionCallRequest(
        function="items.scalar.update",
        actor={"actor_id": "usher-reconcile", "session_id": session_id},
        target={"kind": "item", "item_id": item_id},
        payload={"field": "deploy_stage", "value": stage_name},
        intent="usher_reconcile_github",
    ))
    if getattr(response, "success", False):
        return ""
    err = getattr(response, "error", None)
    return getattr(err, "message", "items.scalar.update failed")


def _error(item_id: int, deploy_stage: str, message: str) -> ReconcileResult:
    return ReconcileResult(outcome="error", item_id=item_id, deploy_stage=deploy_stage, message=message)


def reconcile_item(
    item_id: int,
    *,
    workflow_run_id_override: str = "",
) -> ReconcileResult:
    item_ref = f"YOK-{item_id}"
    deploy_stage = (_yoke_db("items", "get", item_ref, "deploy_stage") or "").strip()
    if not deploy_stage:
        return ReconcileResult(
            outcome="no-action", item_id=item_id,
            message=f"{item_ref} has no deploy_stage set; nothing to reconcile.",
        )
    if not deploy_stage.endswith(_FAILED_SUFFIX):
        return ReconcileResult(
            outcome="no-action", item_id=item_id, deploy_stage=deploy_stage,
            message=(
                f"{item_ref} deploy_stage='{deploy_stage}' does not carry the "
                "'<stage>-failed' shape; nothing to reconcile."
            ),
        )
    stage_name = deploy_stage[: -len(_FAILED_SUFFIX)]

    run_id = _resolve_run_for_item(item_id)
    if not run_id:
        return _error(item_id, deploy_stage, (
            f"{item_ref} has no deployment_run_items row; cannot resolve "
            "Yoke deployment run. Investigate the usher session manually."
        ))

    project, flow = _resolve_project_and_flow(run_id)
    if not project or not flow:
        return _error(item_id, deploy_stage, (
            f"deployment_run '{run_id}' has no project/flow metadata; "
            "cannot resolve workflow."
        ))

    workflow = _resolve_workflow_for_stage(flow, stage_name)
    if not workflow:
        return _error(item_id, deploy_stage, (
            f"flow '{flow}' has no workflow configured for stage '{stage_name}'; "
            "this stage may not use a github-actions executor."
        ))

    github_repo = (_project_db("get", project, "github_repo") or "").strip()
    if not github_repo:
        return _error(item_id, deploy_stage,
                      f"project '{project}' has no github_repo configured.")

    if workflow_run_id_override:
        workflow_run_id = workflow_run_id_override.strip()
    else:
        with connect() as conn:
            checkout = checkout_for_project(conn, project)
        project_repo_path = str(checkout) if checkout is not None else ""
        head_sha = _resolve_head_sha(project_repo_path)
        if not head_sha:
            return _error(item_id, deploy_stage, (
                f"Could not resolve repo HEAD for project '{project}'. "
                "Pass --workflow-run-id <id> with operator-provided evidence."
            ))
        workflow_run_id = _find_workflow_run(github_repo, workflow, head_sha)

    if not workflow_run_id:
        return _error(item_id, deploy_stage, (
            f"No GitHub Actions run found for workflow '{workflow}' at the "
            "current repo HEAD. Pass --workflow-run-id <id> with operator "
            "evidence to reconcile manually."
        ))

    gh = _github_actions("poll", github_repo, workflow_run_id)
    rc, gh_message = gh.returncode, (gh.stdout or "").strip()

    if rc == 0 and gh_message == "success":
        clear_error = _clear_deploy_stage(item_id, stage_name)
        if clear_error:
            return _error(item_id, deploy_stage, clear_error)
        _emit_retroactive_completion(
            run_id=run_id, stage_name=stage_name,
            workflow_run_id=workflow_run_id,
            member_items=[str(item_id)], project=project,
        )
        return ReconcileResult(
            outcome="aligned", item_id=item_id, deploy_stage=deploy_stage,
            workflow_run_id=workflow_run_id, gh_status="completed",
            gh_conclusion="success",
            message=(
                "Yoke records aligned with GitHub truth. "
                f"Resume usher with: /yoke usher {item_ref} --resume"
            ),
        )
    if rc == 1:
        conclusion = gh_message[len("failed:"):] if gh_message.startswith("failed:") else gh_message
        return ReconcileResult(
            outcome="gh-failure", item_id=item_id, deploy_stage=deploy_stage,
            workflow_run_id=workflow_run_id, gh_status="completed",
            gh_conclusion=conclusion or "failed",
            message=(
                f"GitHub Actions agrees the deploy failed ({gh_message}) for run "
                f"{workflow_run_id}. Yoke's deploy_stage='{deploy_stage}' is "
                "correct; no reconciliation needed."
            ),
        )
    if rc in (2, 3):
        return ReconcileResult(
            outcome="gh-running", item_id=item_id, deploy_stage=deploy_stage,
            workflow_run_id=workflow_run_id, gh_status=gh_message,
            message=(
                f"GitHub Actions run {workflow_run_id} is still {gh_message}. "
                "Do not retry yet — wait for GH to reach a terminal state."
            ),
        )
    return ReconcileResult(
        outcome="error", item_id=item_id, deploy_stage=deploy_stage,
        workflow_run_id=workflow_run_id,
        message=(
            f"Unexpected GitHub Actions response (rc={rc}, output='{gh_message}'). "
            "Investigate manually; Yoke state not mutated."
        ),
    )


def _exit_code_for(result: ReconcileResult) -> int:
    if result.outcome in ("aligned", "no-action"):
        return EXIT_OK
    if result.outcome == "gh-running":
        return EXIT_RUNNING
    return EXIT_ERROR


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.engines.usher_reconcile_github",
        description=(
            "Align Yoke records with GitHub Actions truth when an usher "
            "deploy reported failure externally but the GH workflow succeeded."
        ),
    )
    parser.add_argument("item", help="Item ref (PREFIX-N).")
    parser.add_argument(
        "--workflow-run-id", default="",
        help="Operator-provided GitHub Actions run id (skips repo-HEAD lookup).",
    )
    args = parser.parse_args(argv)

    try:
        item_id = _parse_item_id(args.item)
    except (ValueError, TypeError):
        print(f"Error: cannot parse item id '{args.item}'", file=sys.stderr)
        return EXIT_USAGE

    result = reconcile_item(item_id, workflow_run_id_override=args.workflow_run_id)
    stream = sys.stderr if result.outcome == "error" else sys.stdout
    prefix = "Error: " if result.outcome == "error" else ""
    print(f"{prefix}{result.message}", file=stream)
    return _exit_code_for(result)


if __name__ == "__main__":
    sys.exit(main())
