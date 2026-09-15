"""Align Yoke deploy records with GitHub Actions truth."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain.deploy_pipeline_reporting import _github_actions
from yoke_core.engines.usher_reconcile_github_verdict import (
    ReconcileResult,
    error as _error,
    reconcile_from_gh_poll as _reconcile_from_gh_poll,
)


EXIT_OK, EXIT_ERROR, EXIT_RUNNING, EXIT_USAGE = 0, 1, 2, 3

_FAILED_SUFFIX = "-failed"


def _parse_item_argument(arg: str | int) -> int:
    """Resolve an item ref to the internal ``items.id``.

    ``PREFIX-N`` maps to the project's ``public_item_prefix`` +
    ``items.project_sequence``; a bare number uses the mapped checkout project.
    """
    if arg is None or (isinstance(arg, str) and not arg.strip()):
        raise ValueError("missing item id")
    from yoke_core.domain.yok_n_parser import parse_item_argument

    return parse_item_argument(arg)


def _resolve_run_for_item(item_id: int) -> str:
    response = call_dispatcher(
        function_id="deployment_runs.find_by_item",
        target=TargetRef(kind="item", item_id=item_id),
        payload={},
    )
    rows = (response.result or {}).get("rows") if response.success else []
    if not rows:
        return ""
    return str(rows[0].get("id") or "")


def _item_deploy_stage(item_id: int) -> str:
    response = call_dispatcher(
        function_id="items.get.run",
        target=TargetRef(kind="item", item_id=item_id),
        payload={"fields": ["deploy_stage"]},
    )
    if not response.success:
        return ""
    fields = (response.result or {}).get("fields") or {}
    return str(fields.get("deploy_stage") or "")


def _resolve_workflow_for_stage(stages: list[dict], stage_name: str) -> str:
    for stage in stages:
        if stage.get("name") == stage_name:
            return stage.get("workflow", "") or ""
    return ""


def _find_workflow_run(
    github_repo: str,
    workflow: str,
    head_sha: str,
    *,
    project: str,
) -> str:
    r = _github_actions(
        "find-run",
        github_repo,
        workflow,
        head_sha,
        project=project,
    )
    run_id = (r.stdout or "").strip()
    return "" if not run_id or run_id == "not_found" else run_id


def _display_item_ref(item_id: int) -> str:
    """Render a public item ref without making reconciliation depend on it."""
    from yoke_core.domain.project_identity_item_ref import item_ref_for_id

    return item_ref_for_id(int(item_id))


def reconcile_item(
    item_id: int,
    *,
    workflow_run_id_override: str = "",
) -> ReconcileResult:
    # The nested item CLI boundary receives the canonical public ref, never a
    # stringified internal id that it could reinterpret as a public sequence.
    public_ref = _display_item_ref(item_id)
    deploy_stage = _item_deploy_stage(item_id).strip()
    if not deploy_stage:
        return ReconcileResult(
            outcome="no-action",
            item_id=item_id,
            message=f"{public_ref} has no deploy_stage set; nothing to reconcile.",
        )
    if not deploy_stage.endswith(_FAILED_SUFFIX):
        return ReconcileResult(
            outcome="no-action",
            item_id=item_id,
            deploy_stage=deploy_stage,
            message=(
                f"{public_ref} deploy_stage='{deploy_stage}' does not carry the "
                "'<stage>-failed' shape; nothing to reconcile."
            ),
        )
    stage_name = deploy_stage[: -len(_FAILED_SUFFIX)]

    run_id = _resolve_run_for_item(item_id)
    if not run_id:
        return _error(
            item_id,
            deploy_stage,
            (
                f"{public_ref} has no deployment_run_items row; cannot resolve "
                "Yoke deployment run. Investigate the usher session manually."
            ),
        )

    try:
        context = control_plane.execution_context(run_id)
    except control_plane.DeploymentControlPlaneError as exc:
        return _error(item_id, deploy_stage, str(exc))
    run = context.get("run") or {}
    project, flow = str(run.get("project") or ""), str(run.get("flow") or "")
    if not project or not flow:
        return _error(
            item_id,
            deploy_stage,
            (
                f"deployment_run '{run_id}' has no project/flow metadata; "
                "cannot resolve workflow."
            ),
        )

    workflow = _resolve_workflow_for_stage(context.get("stages") or [], stage_name)
    if not workflow:
        return _error(
            item_id,
            deploy_stage,
            (
                f"flow '{flow}' has no workflow configured for stage '{stage_name}'; "
                "this stage may not use a github-actions executor."
            ),
        )

    try:
        github_repo = control_plane.project_field(project, "github_repo")
    except control_plane.DeploymentControlPlaneError as exc:
        return _error(item_id, deploy_stage, str(exc))
    if not github_repo:
        return _error(
            item_id,
            deploy_stage,
            f"project '{project}' has no registered github_repo; cannot look "
            "up GitHub Actions runs.",
        )

    head_sha = ""
    if workflow_run_id_override:
        workflow_run_id = workflow_run_id_override.strip()
    else:
        # The run's own recorded lineage is the evidence this reconcile is
        # actually about — the commit that run built. Whoever invokes this
        # recovery command may hold no checkout at all, or one on a
        # different commit than the one the run actually shipped, so a
        # local git HEAD is never a substitute for the run's own record.
        head_sha = str(run.get("release_lineage") or "")
        if not head_sha:
            return _error(
                item_id,
                deploy_stage,
                (
                    f"deployment_run '{run_id}' has no recorded release_lineage; "
                    "there is no authoritative commit to look up a GitHub "
                    "Actions run for. Pass --workflow-run-id <id> with "
                    "operator-provided evidence to reconcile manually."
                ),
            )
        workflow_run_id = _find_workflow_run(
            github_repo,
            workflow,
            head_sha,
            project=project,
        )

    if not workflow_run_id:
        return _error(
            item_id,
            deploy_stage,
            (
                f"No GitHub Actions run found for workflow '{workflow}' at the "
                f"run's own recorded commit '{head_sha}'. Pass --workflow-run-id "
                "<id> with operator evidence to reconcile manually."
            ),
        )

    gh = _github_actions(
        "poll",
        github_repo,
        workflow_run_id,
        project=project,
    )
    return _reconcile_from_gh_poll(
        gh,
        item_id=item_id,
        deploy_stage=deploy_stage,
        stage_name=stage_name,
        run_id=run_id,
        workflow_run_id=workflow_run_id,
        project=project,
        public_ref=public_ref,
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
        "--workflow-run-id",
        default="",
        help="Operator-provided GitHub Actions run id (skips the release_lineage lookup).",
    )
    args = parser.parse_args(argv)

    try:
        item_id = _parse_item_argument(args.item)
    except (ValueError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    result = reconcile_item(item_id, workflow_run_id_override=args.workflow_run_id)
    stream = sys.stderr if result.outcome == "error" else sys.stdout
    prefix = "Error: " if result.outcome == "error" else ""
    print(f"{prefix}{result.message}", file=stream)
    return _exit_code_for(result)


if __name__ == "__main__":
    sys.exit(main())
