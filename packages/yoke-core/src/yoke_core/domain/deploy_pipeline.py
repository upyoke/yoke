"""Deployment pipeline orchestration — stage iteration, executor dispatch, CI gates.

Canonical Python owner of the deployment pipeline. Retired the
``deploy-pipeline.sh`` thin launcher; invoke this module directly instead.

CLI usage::

    python3 -m yoke_core.domain.deploy_pipeline <run-id|item-id> [--timeout M] [--from-stage S] [--fresh]

Exit codes: 0 = success, 1 = stage failed, 2 = awaiting approval, 3 = usage/setup error.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, query_one, query_rows, query_scalar
from yoke_core.domain import deploy_qa_recorder
from yoke_core.domain.deploy_pipeline_executors import (
    _dispatch_ephemeral_verify,
    _dispatch_executor,
    _dispatch_github_actions_workflow,
)
from yoke_core.domain.deploy_pipeline_gates import (
    _resolve_and_verify_branch,
    resolve_flow_gate_branch,
)
from yoke_core.domain.deploy_pipeline_reporting import (
    _emit_run_event,
    _flow_db,
    _parse_stages,
    _project_db,
    _resolve_script_dir,
    _set_deploy_stage,
    _yoke_db,
)
from yoke_core.domain.deployment_flow_seed_stage import ensure_seed_stage
from yoke_core.domain.flow_init import _SEED_FLOWS
from yoke_core.domain.project_checkout_locations import checkout_for_project


EXIT_SUCCESS = 0
EXIT_STAGE_FAILED = 1
EXIT_AWAITING_APPROVAL = 2
EXIT_USAGE = 3
_SEEDED_FLOW_IDS = frozenset(str(flow["id"]) for flow in _SEED_FLOWS)
_SEEDED_STAGE_REPAIRS = {
    "yoke-prod-release": ("distribution-publish", "complete"),
    "yoke-stage-release": ("distribution-publish", "complete"),
}
_RELEASE_CONTROL_PLANE_ENV_VAR = "YOKE_RELEASE_CONTROL_PLANE_ENV"


def _normalize_release_control_plane_env(value: str) -> str:
    """Return the environment label for release-run metadata authority."""
    label = value.strip()
    if label.endswith("-db-admin"):
        return label[: -len("-db-admin")]
    return label


def _release_control_plane_env() -> str:
    """Describe where deployment run metadata is being written."""
    explicit = os.environ.get(_RELEASE_CONTROL_PLANE_ENV_VAR, "")
    if explicit.strip():
        return _normalize_release_control_plane_env(explicit)

    active_env = os.environ.get("YOKE_ENV", "")
    if active_env.strip():
        return _normalize_release_control_plane_env(active_env)

    if os.environ.get("YOKE_PG_DSN", "").strip():
        return "dsn"

    return "ambient"


def _converge_seeded_flow_config(flow_id: str) -> None:
    """Repair seed-owned deployment-flow rows before stage dispatch."""
    if flow_id not in _SEEDED_FLOW_IDS:
        return
    repair = _SEEDED_STAGE_REPAIRS.get(flow_id)
    if repair is None:
        return
    conn = connect()
    try:
        stage_name, before_stage = repair
        ensure_seed_stage(
            conn,
            seed_flows=_SEED_FLOWS,
            flow_id=flow_id,
            stage_name=stage_name,
            before_stage=before_stage,
        )
        conn.commit()
    finally:
        conn.close()
    print(f"Seeded deployment flow config converged: {flow_id}")


def run_pipeline(
    primary_arg: str,
    *,
    timeout_min: int = 30,
    from_stage: str = "",
    fresh: bool = False,
    image_tag: str = "",
    sd: Optional[str] = None,
) -> int:
    """Execute the deployment pipeline.  Returns exit code."""
    sd = sd or _resolve_script_dir()

    # --- Determine mode ---
    run_id, project, flow_id = "", "", ""
    run_status, current_stage = "", ""
    member_items: List[str] = []

    if primary_arg.startswith("run-"):
        # Run-based path
        run_id = primary_arg
        run_row = _yoke_db("runs", "get", run_id, sd=sd)
        if not run_row:
            print(f"Error: deployment run '{run_id}' not found", file=sys.stderr)
            return EXIT_USAGE

        fields = run_row.split("|")
        project = fields[1] if len(fields) > 1 else ""
        flow_id = fields[2] if len(fields) > 2 else ""
        run_status = fields[5] if len(fields) > 5 else ""
        current_stage = fields[6] if len(fields) > 6 else ""

        items_output = _yoke_db("runs", "items", run_id, sd=sd)
        if items_output:
            member_items = [line.split("|")[1] for line in items_output.strip().split("\n") if "|" in line]

        if not member_items:
            # Environment-level deploys (stage bootstrap, operator
            # redeploys) carry zero items by design; item-bound behavior
            # applies only when items are attached.
            print(f"Run {run_id} has no member items (environment-level deploy)")
    else:
        # Legacy item-based path
        item_num = primary_arg.replace("YOK-", "").replace("yok-", "")
        print("Warning: Legacy item-based pipeline invocation. Auto-creating a deployment run.", file=sys.stderr)

        flow_id = _yoke_db("items", "get", f"YOK-{item_num}", "deployment_flow", sd=sd)
        project = _yoke_db("items", "get", f"YOK-{item_num}", "project", sd=sd)

        if not flow_id:
            print(f"Error: YOK-{item_num} has no deployment_flow assigned", file=sys.stderr)
            return EXIT_USAGE
        if not project:
            print(f"Error: YOK-{item_num} has no project assigned", file=sys.stderr)
            return EXIT_USAGE

        run_id = _yoke_db("runs", "create-run", project, flow_id, "--created-by", "system", sd=sd)
        if not run_id:
            print(f"Error: failed to auto-create deployment run for YOK-{item_num}", file=sys.stderr)
            return EXIT_USAGE

        _yoke_db("runs", "add-item", run_id, item_num, sd=sd)
        member_items = [item_num]
        run_status = "created"
        print(f"Auto-created run {run_id} for YOK-{item_num}")

    if not flow_id:
        print(f"Error: deployment run '{run_id}' has no flow assigned", file=sys.stderr)
        return EXIT_USAGE

    try:
        _converge_seeded_flow_config(flow_id)
    except Exception as exc:
        print(
            f"Error: failed to converge seeded deployment flow '{flow_id}': {exc}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    # --- Read stages ---
    stages_json = _flow_db("stages", flow_id, sd=sd)
    if not stages_json:
        print(f"Error: deployment flow '{flow_id}' not found or has no stages", file=sys.stderr)
        return EXIT_USAGE

    stages = _parse_stages(stages_json)
    if not stages:
        print(f"Error: no stages found in flow '{flow_id}'", file=sys.stderr)
        return EXIT_USAGE

    # --- Resolve project repo info ---
    github_repo = _project_db("get", project, "github_repo", sd=sd) if project else ""
    project_repo_path = ""
    if project:
        conn = connect()
        try:
            checkout = checkout_for_project(conn, project)
        finally:
            conn.close()
        project_repo_path = str(checkout) if checkout is not None else ""

    # Flow target environment, consumed by env-aware executors.
    target_env = _flow_db("get", flow_id, "target_env", sd=sd)
    target_env = "" if target_env == "null" else target_env
    print(
        "Deployment authority: "
        f"release_control_plane={_release_control_plane_env()} "
        f"target_env={target_env or '<unset>'} "
        f"flow={flow_id} run={run_id}"
    )

    # The branch this flow gates on: the target env's declared deploy
    # branch (environments.settings.git.branch), else the project base
    # branch. Consumed by the merged gate and the CI gate.
    gate_branch = resolve_flow_gate_branch(project, target_env, project_repo_path)

    # --- Branch verification (item-bound; item-less runs skip it) ---
    ok, first_item, branch = _resolve_and_verify_branch(
        member_items, project_repo_path, target_branch=gate_branch, sd=sd,
    )
    if not ok:
        return EXIT_USAGE

    # --- Seed QA ---
    deploy_qa_recorder.cmd_seed_from_flow(run_id, script_dir=sd)

    # --- Determine start position ---
    start_stage = from_stage
    if not start_stage and current_stage:
        if current_stage.endswith("-failed"):
            start_stage = current_stage.replace("-failed", "")
        elif current_stage == "complete":
            print(f"Pipeline already complete for run {run_id}")
            return EXIT_SUCCESS
        else:
            start_stage = current_stage

    # --- Stage iteration ---
    found_start = not start_stage  # True if no resume point
    run_started = run_status != "created"

    for stage in stages:
        s_name = stage["name"]

        if not found_start:
            if s_name == start_stage:
                found_start = True
            else:
                continue

        print(f"--- Stage: {s_name} (executor: {stage['executor']}) ---")

        # Start run execution on first stage
        if not run_started:
            _yoke_db("runs", "update", run_id, "status", "executing", sd=sd)
            _emit_run_event(
                "DeploymentRunExecuting", "started",
                {"run_id": run_id, "flow": flow_id, "project": project},
                member_items=member_items, project=project, sd=sd,
            )
            # Transition member items to release
            for sri_item in member_items:
                sri_status = _yoke_db("items", "get", f"YOK-{sri_item}", "status", sd=sd)
                if sri_status == "implemented":
                    env = dict(os.environ)
                    env["YOKE_CLAIM_BYPASS"] = f"deploy-pipeline:run-{run_id}"
                    subprocess.run(
                        [sys.executable, "-m", "yoke_core.cli.db_router",
                         "items", "update", sri_item, "status", "release"],
                        capture_output=True, env=env,
                    )
            run_started = True

        # Update deploy_stage
        _set_deploy_stage(s_name, run_id, member_items, sd=sd)

        # Emit stage started
        _emit_run_event(
            "DeploymentRunStageStarted", "started",
            {"run_id": run_id, "stage": s_name, "executor": stage["executor"], "flow": flow_id},
            member_items=member_items, project=project, sd=sd,
        )

        # Dispatch executor
        exec_rc, exec_diag = _dispatch_executor(
            stage,
            run_id=run_id,
            member_items=member_items,
            github_repo=github_repo,
            project=project,
            project_repo_path=project_repo_path,
            branch=branch,
            first_item=first_item,
            timeout_min=timeout_min,
            fresh=fresh,
            image_tag=image_tag,
            target_env=target_env,
            gate_branch=gate_branch,
            sd=sd,
        )

        # Special return codes
        if exec_rc == -2:
            # Awaiting human approval
            return EXIT_AWAITING_APPROVAL
        if exec_rc == -3:
            # Executor pre-emitted the stage completion event (e.g.
            # ephemeral-verify preview URL, github-actions reconcile-from-truth).
            print(f"  Stage '{s_name}' completed successfully")
            deploy_qa_recorder.cmd_record_stage_result(
                run_id, s_name, "pass", script_dir=sd,
            )
            continue

        # Handle result
        if exec_rc == 0:
            _emit_run_event(
                "DeploymentRunStageCompleted", "completed",
                {"run_id": run_id, "stage": s_name, "result": "success"},
                member_items=member_items, project=project, sd=sd,
            )
            print(f"  Stage '{s_name}' completed successfully")
            deploy_qa_recorder.cmd_record_stage_result(
                run_id, s_name, "pass", script_dir=sd,
            )
        else:
            failure_ctx = {"run_id": run_id, "stage": s_name, "result": "failed", "exit_code": exec_rc}
            if exec_diag:
                failure_ctx["executor_diagnostic"] = exec_diag
            _emit_run_event(
                "DeploymentRunStageFailed", "failed",
                failure_ctx,
                member_items=member_items, project=project, sd=sd,
            )
            _set_deploy_stage(f"{s_name}-failed", run_id, member_items, sd=sd)
            deploy_qa_recorder.cmd_record_stage_result(
                run_id, s_name, "fail", script_dir=sd,
            )
            _yoke_db("runs", "update", run_id, "status", "failed", sd=sd)
            _emit_run_event(
                "DeploymentRunFailed", "failed",
                {"run_id": run_id, "stage": s_name, "flow": flow_id},
                member_items=member_items, project=project, sd=sd,
            )
            print(f"Error: stage '{s_name}' failed (exit code: {exec_rc})", file=sys.stderr)
            return EXIT_STAGE_FAILED

    # Guard: start_stage never matched
    if not found_start:
        print(f"Error: start stage '{start_stage}' not found in flow '{flow_id}'", file=sys.stderr)
        print("Available stages:", file=sys.stderr)
        for s in stages:
            print(f"  {s['name']}", file=sys.stderr)
        return EXIT_USAGE

    # --- Pipeline complete ---
    _set_deploy_stage("complete", run_id, member_items, sd=sd)

    # Check blocking QA before marking succeeded
    conn = connect()
    try:
        pending_blocking = query_scalar(
            conn,
            "SELECT COUNT(*) FROM deployment_run_qa WHERE run_id=%s AND blocking=1 AND status='pending'",
            (run_id,),
        )
        if pending_blocking and pending_blocking > 0:
            pending_checks = [
                row[0] for row in query_rows(
                    conn,
                    "SELECT check_name FROM deployment_run_qa WHERE run_id=%s AND blocking=1 AND status='pending'",
                    (run_id,),
                )
            ]
            print(f"Warning: {pending_blocking} blocking QA check(s) still pending for run {run_id}", file=sys.stderr)
            if pending_checks:
                print(f"  Pending checks: {', '.join(pending_checks)}", file=sys.stderr)
    finally:
        conn.close()

    _yoke_db("runs", "update", run_id, "status", "succeeded", sd=sd)
    _emit_run_event(
        "DeploymentRunSucceeded", "completed",
        {"run_id": run_id, "flow": flow_id, "project": project},
        member_items=member_items, project=project, sd=sd,
    )

    # Auto-set deployed_to (item-bound; no-op for item-less runs)
    if target_env and member_items:
        for item_id in member_items:
            _yoke_db("items", "update", item_id, "deployed_to", target_env, sd=sd)
        print(f"Auto-set deployed_to={target_env} from flow {flow_id}")

    print(f"Pipeline complete for run {run_id}")
    return EXIT_SUCCESS


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deploy-pipeline",
        description="Deployment pipeline orchestrator",
    )
    p.add_argument("primary_arg", help="run-ID or item-ID")
    p.add_argument("--timeout", type=int, default=30, help="Timeout in minutes")
    p.add_argument("--from-stage", default="", help="Resume from this stage")
    p.add_argument("--fresh", action="store_true", help="Skip existing-run search")
    p.add_argument(
        "--image-tag",
        default="",
        help="Explicit core image tag for item-less environment deploys",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return run_pipeline(
        args.primary_arg,
        timeout_min=args.timeout,
        from_stage=args.from_stage,
        fresh=args.fresh,
        image_tag=args.image_tag,
    )


if __name__ == "__main__":
    sys.exit(main())
