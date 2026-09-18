"""Deployment pipeline orchestration for stages, runners, and CI gates."""

from __future__ import annotations

import json
import sys
from typing import List, Optional

from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain import deploy_pipeline_stage_receipt as stage_receipt
from yoke_core.domain import deploy_pipeline_environment as deploy_env
from yoke_core.domain import deploy_pipeline_run_updates as run_updates
from yoke_core.domain.deploy_pipeline_gates import (
    _resolve_and_verify_branch,
    resolve_flow_gate_branch,
)
from yoke_core.domain.deploy_pipeline_events import emit_run_event as _emit_run_event
from yoke_core.domain import deploy_pipeline_failure
from yoke_core.domain.deploy_pipeline_reporting import (
    _parse_stages,
    _resolve_script_dir,
    _set_deploy_stage,
)
from yoke_core.domain.deploy_pipeline_run_context import (
    EXIT_FINALIZATION_PENDING,  # noqa: F401 — public pipeline exit 4
    complete_run_finalization,
    resolve_project_checkout_path,
)
from yoke_core.domain import deploy_pipeline_stage_checks as stage_checks
from yoke_core.domain.deployment_item_stamp import transition_member_to_release
from yoke_core.domain.deployment_run_carried_membership import describe_enrollment
from yoke_core.domain.deploy_product_source import (
    DeployProductSourceError,
    validate_itemless_product_source,
)
from yoke_core.domain.deploy_pipeline_cli import _build_parser  # noqa: F401


EXIT_SUCCESS = 0
EXIT_STAGE_FAILED = deploy_pipeline_failure.EXIT_STAGE_FAILED
EXIT_AWAITING_APPROVAL = 2
EXIT_USAGE = 3
EXIT_AWAITING_QA = 5
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

    if not primary_arg.startswith("run-"):
        print(
            "Error: deployment execution requires a run ID; compose an "
            "item-bound run with `yoke deployment-runs start-for-item ITEM`, "
            "then execute the returned run ID",
            file=sys.stderr,
        )
        return EXIT_USAGE
    run_id = primary_arg
    try:
        context = control_plane.execution_context(run_id)
    except control_plane.DeploymentControlPlaneError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    run = context.get("run") or {}
    members = context.get("members") or []
    project = str(run.get("project") or "")
    flow_id = str(run.get("flow") or "")
    release_lineage = str(run.get("release_lineage") or "")
    qa_result = (
        json.dumps({"verification_tree": {"head_sha": release_lineage}})
        if release_lineage
        else "{}"
    )
    run_status = str(run.get("status") or "")
    current_stage = str(run.get("current_stage") or "")
    member_items = [str(member["item_id"]) for member in members]
    member_statuses = {
        str(member["item_id"]): str(member.get("status") or "") for member in members
    }
    first_member = members[0] if members else {}
    enrollment = describe_enrollment(context.get("enrolled_carried_items") or ())
    if enrollment:
        print(enrollment)
    if not member_items:
        print(f"Run {run_id} has no member items (environment-level deploy)")

    if not flow_id:
        print(f"Error: deployment run '{run_id}' has no flow assigned", file=sys.stderr)
        return EXIT_USAGE
    try:
        product_source = validate_itemless_product_source(
            product_repo_path, image_tag, member_items
        )
    except (DeployProductSourceError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    product_repo_path = product_source.repo_path if product_source else ""
    image_tag = product_source.image_tag if product_source else image_tag
    raw_stages = context.get("stages")
    if not isinstance(raw_stages, list):
        print(
            f"Error: deployment flow '{flow_id}' not found or has no stages",
            file=sys.stderr,
        )
        return EXIT_USAGE
    stages = _parse_stages(json.dumps(raw_stages))
    if not stages:
        print(f"Error: no stages found in flow '{flow_id}'", file=sys.stderr)
        return EXIT_USAGE

    try:
        github_repo = control_plane.project_field(project, "github_repo")
    except control_plane.DeploymentControlPlaneError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    project_repo_path = resolve_project_checkout_path(project)

    target_tier = str(run.get("target_tier") or "")
    environment_name = str(run.get("target_environment") or "")
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
        project,
        target_tier,
        environment_name,
        project_repo_path,
    )

    ok, first_item, branch = _resolve_and_verify_branch(
        member_items,
        project_repo_path,
        target_branch=gate_branch,
        first_branch=str(first_member.get("branch") or ""),
        first_item_label=str(first_member.get("public_ref") or ""),
        sd=sd,
    )
    if not ok:
        return EXIT_USAGE

    try:
        control_plane.seed_qa(run_id)
    except control_plane.DeploymentControlPlaneError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    # --- Determine start position ---
    start_stage = from_stage
    if not start_stage and current_stage:
        if current_stage.endswith("-failed"):
            start_stage = current_stage.replace("-failed", "")
        elif current_stage == "complete":
            if run_status == "succeeded":
                print(f"Pipeline already complete for run {run_id}")
                return EXIT_SUCCESS
            return complete_run_finalization(
                run_id,
                flow_id,
                project,
                member_items,
                target_tier,
                environment_name,
                sd=sd,
            )
        else:
            start_stage = current_stage

    if start_stage:
        resume_exit = stage_checks.check_resume_qa_gate(
            run_id=run_id,
            start_stage=start_stage,
            stage_failed_exit=EXIT_STAGE_FAILED,
            awaiting_qa_exit=EXIT_AWAITING_QA,
        )
        if resume_exit is not None:
            return resume_exit

    # --- Stage iteration ---
    found_start = not start_stage  # True if no resume point
    # Same-run --from-stage of a failed/cancelled run must re-enter executing
    # before stage_receipt_allocate; skipped completed stages are not replayed.
    run_started = run_status not in {"created", "failed", "cancelled"}

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
            run_updates.update_run_field(run_id, "status", "executing")
            _emit_run_event(
                "DeploymentRunExecuting",
                "started",
                {"run_id": run_id, "flow": flow_id, "project": project},
                member_items=member_items,
                project=project,
                sd=sd,
            )
            # Transition member items to release
            for sri_item in member_items:
                if member_statuses.get(sri_item) == "implemented":
                    transition_member_to_release(int(sri_item), run_id)
            run_started = True

        # Update deploy_stage
        _set_deploy_stage(s_name, run_id, member_items, sd=sd)

        # Emit stage started
        _emit_run_event(
            "DeploymentRunStageStarted",
            "started",
            {
                "run_id": run_id,
                "stage": s_name,
                "step_runner": stage["step_runner"],
                "flow": flow_id,
            },
            member_items=member_items,
            project=project,
            sd=sd,
        )

        # Dispatch step_runner
        exec_rc, exec_diag = stage_receipt.dispatch_step_runner_with_receipt(
            stage,
            stages=stages,
            run_id=run_id,
            member_items=member_items,
            github_repo=github_repo,
            project=project,
            project_repo_path=project_repo_path,
            product_repo_path=product_repo_path,
            branch=branch,
            first_item=first_item,
            first_item_label=str(first_member.get("public_ref") or ""),
            timeout_min=timeout_min,
            fresh=fresh,
            image_tag=image_tag,
            environment_name=environment_name,
            gate_branch=gate_branch,
            release_lineage=release_lineage,
            run_artifact_identity=str(run.get("artifact_identity") or ""),
            target_identity=context.get("target_identity") or {},
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
            control_plane.record_qa_pass(run_id, s_name, qa_result)
            continue
        if exec_rc == -4:
            print(
                f"  Stage '{s_name}' is awaiting scoped QA: {exec_diag}",
                file=sys.stderr,
            )
            return EXIT_AWAITING_QA

        # Handle result
        if exec_rc == 0:
            _emit_run_event(
                "DeploymentRunStageCompleted",
                "completed",
                {"run_id": run_id, "stage": s_name, "result": "success"},
                member_items=member_items,
                project=project,
                sd=sd,
            )
            print(f"  Stage '{s_name}' completed successfully")
            control_plane.record_qa_pass(run_id, s_name, qa_result)
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
        stage_checks.report_missing_start_stage(flow_id, start_stage, stages)
        return EXIT_USAGE

    # --- Pipeline complete ---
    _set_deploy_stage("complete", run_id, member_items, sd=sd)

    qa_exit = stage_checks.check_unresolved_qa(
        run_id, usage_exit=EXIT_USAGE, awaiting_qa_exit=EXIT_AWAITING_QA
    )
    if qa_exit is not None:
        return qa_exit

    return complete_run_finalization(
        run_id,
        flow_id,
        project,
        member_items,
        target_tier,
        environment_name,
        sd=sd,
    )


def main(argv: Optional[List[str]] = None) -> int:
    from yoke_core.domain.deploy_pipeline_cli import main as cli_main

    return cli_main(argv, runner=run_pipeline)


if __name__ == "__main__":
    sys.exit(main())
