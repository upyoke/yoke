"""Deployment pipeline orchestration for stages, runners, and CI gates."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain import deploy_qa_recorder
from yoke_core.domain.claim_recovery import canonical_item_ref
from yoke_core.domain.deploy_pipeline_step_runners import (
    _dispatch_step_runner,
)
from yoke_core.domain import deploy_pipeline_environment as deploy_env
from yoke_core.domain.deploy_pipeline_gates import (
    _resolve_and_verify_branch,
    resolve_flow_gate_branch,
)
from yoke_core.domain.deploy_pipeline_events import emit_run_event as _emit_run_event
from yoke_core.domain import deploy_pipeline_failure
from yoke_core.domain.deploy_pipeline_reporting import (
    _flow_db,
    _parse_stages,
    _project_db,
    _resolve_script_dir,
    _set_deploy_stage,
    _yoke_db,
)
from yoke_core.domain.deploy_pipeline_run_context import (
    finalize_run_success,
    resolve_flow_target,
    resolve_project_checkout_path,
)
from yoke_core.domain.deployment_item_stamp import (
    transition_member_to_release,
)
from yoke_core.domain.deploy_product_source import DeployProductSourceError, validate_itemless_product_source


EXIT_SUCCESS = 0
EXIT_STAGE_FAILED = deploy_pipeline_failure.EXIT_STAGE_FAILED
EXIT_AWAITING_APPROVAL = 2
EXIT_USAGE = 3
_release_control_plane_env = deploy_env.release_control_plane_env


def run_pipeline(
    primary_arg: str,
    *,
    timeout_min: int = 30,
    from_stage: str = "",
    fresh: bool = False,
    image_tag: str = "",
    product_repo_path: str = "",
    sd: Optional[str] = None,
) -> int:
    """Execute the deployment pipeline.  Returns exit code."""
    sd = sd or _resolve_script_dir()

    run_id, project, flow_id = "", "", ""
    run_status, current_stage, release_lineage = "", "", ""
    member_items: List[str] = []

    if primary_arg.startswith("run-"):
        run_id = primary_arg
        run_row = _yoke_db("runs", "get", run_id, sd=sd)
        if not run_row:
            print(deploy_env.run_not_found_message(run_id), file=sys.stderr)
            return EXIT_USAGE

        fields = run_row.split("|")
        project = fields[1] if len(fields) > 1 else ""
        flow_id = fields[2] if len(fields) > 2 else ""
        release_lineage = fields[5] if len(fields) > 5 else ""
        run_status = fields[6] if len(fields) > 6 else ""
        current_stage = fields[7] if len(fields) > 7 else ""

        items_output = _yoke_db("runs", "items", run_id, sd=sd)
        if items_output:
            member_items = [line.split("|")[1] for line in items_output.strip().split("\n") if "|" in line]

        if not member_items:
            print(f"Run {run_id} has no member items (environment-level deploy)")
    else:
        from yoke_core.domain.deploy_pipeline_item_run import (
            create_run_for_item_ref,
        )

        item_run = create_run_for_item_ref(primary_arg, sd=sd)
        if item_run is None:
            return EXIT_USAGE
        run_id = item_run.run_id
        project = item_run.project
        flow_id = item_run.flow_id
        member_items = list(item_run.member_items)
        run_status = "created"

    if not flow_id:
        print(f"Error: deployment run '{run_id}' has no flow assigned", file=sys.stderr)
        return EXIT_USAGE
    try:
        product_source = validate_itemless_product_source(
            product_repo_path, image_tag, member_items,
        )
    except (DeployProductSourceError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    product_repo_path = product_source.repo_path if product_source else ""
    image_tag = product_source.image_tag if product_source else image_tag
    stages_json = _flow_db("stages", flow_id, sd=sd)
    if not stages_json:
        print(f"Error: deployment flow '{flow_id}' not found or has no stages", file=sys.stderr)
        return EXIT_USAGE

    stages = _parse_stages(stages_json)
    if not stages:
        print(f"Error: no stages found in flow '{flow_id}'", file=sys.stderr)
        return EXIT_USAGE

    github_repo = _project_db("get", project, "github_repo", sd=sd) if project else ""
    project_repo_path = resolve_project_checkout_path(project)

    target_tier, environment_name = resolve_flow_target(
        flow_id, sd=sd,
    )
    print(
        "Deployment authority: "
        f"release_control_plane={deploy_env.release_control_plane_env()} "
        f"target={environment_name or target_tier or '<unset>'} "
        f"flow={flow_id} run={run_id}"
    )

    # The branch this flow gates on: the referenced environment's declared
    # deploy branch (environments.settings.git.branch), else the project
    # base branch. Consumed by the merged gate and the CI gate.
    gate_branch = resolve_flow_gate_branch(
        project, target_tier, environment_name, project_repo_path,
    )

    ok, first_item, branch = _resolve_and_verify_branch(
        member_items, project_repo_path, target_branch=gate_branch, sd=sd,
    )
    if not ok:
        return EXIT_USAGE

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

        print(f"--- Stage: {s_name} (step_runner: {stage['step_runner']}) ---")

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
                sri_ref = canonical_item_ref(int(sri_item))
                if sri_ref is None:
                    print(f"Error: cannot render deployment member items.id={sri_item}", file=sys.stderr)
                    return EXIT_USAGE
                sri_status = _yoke_db("items", "get", sri_ref, "status", sd=sd)
                if sri_status == "implemented":
                    transition_member_to_release(int(sri_item), run_id)
            run_started = True

        # Update deploy_stage
        _set_deploy_stage(s_name, run_id, member_items, sd=sd)

        # Emit stage started
        _emit_run_event(
            "DeploymentRunStageStarted", "started",
            {"run_id": run_id, "stage": s_name, "step_runner": stage["step_runner"], "flow": flow_id},
            member_items=member_items, project=project, sd=sd,
        )

        # Dispatch step_runner
        exec_rc, exec_diag = _dispatch_step_runner(
            stage,
            run_id=run_id,
            member_items=member_items,
            github_repo=github_repo,
            project=project,
            project_repo_path=project_repo_path,
            product_repo_path=product_repo_path,
            branch=branch,
            first_item=first_item,
            timeout_min=timeout_min,
            fresh=fresh,
            image_tag=image_tag,
            environment_name=environment_name,
            gate_branch=gate_branch,
            release_lineage=release_lineage,
            sd=sd,
        )

        # Special return codes
        if exec_rc == -2:
            # Awaiting human approval
            return EXIT_AWAITING_APPROVAL
        if exec_rc == -3:
            # Step runner pre-emitted the stage completion event (e.g.
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
            return deploy_pipeline_failure.fail_pipeline_stage(
                exit_code=exec_rc,
                diagnostic=exec_diag,
                stage_name=s_name,
                run_id=run_id,
                flow_id=flow_id,
                member_items=member_items,
                project=project,
                sd=sd,
                emit_event=_emit_run_event,
            )

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

    finalize_run_success(
        run_id, flow_id, project, member_items, target_tier,
        environment_name, sd=sd)
    print(f"Pipeline complete for run {run_id}")
    return EXIT_SUCCESS


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deploy-pipeline",
        description="Deployment pipeline orchestrator",
    )
    p.add_argument("primary_arg", help="run-ID or item-ID")
    p.add_argument("--timeout", type=int, default=30, help="Timeout in minutes")
    p.add_argument("--from-stage", default="", help="Resume from this stage")
    p.add_argument("--fresh", action="store_true", help="Skip existing-run search")
    p.add_argument("--product-repo-path", default="", help="Pinned product checkout for an itemless environment deploy")
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
        product_repo_path=args.product_repo_path,
    )


if __name__ == "__main__":
    sys.exit(main())
