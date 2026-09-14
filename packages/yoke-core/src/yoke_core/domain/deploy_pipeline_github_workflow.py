"""github-actions-workflow stage step_runner — CI gate, trigger, reconcile, poll.

Split from :mod:`yoke_core.domain.deploy_pipeline_step_runners` so the
dispatch table stays small; the dispatcher delegates the
``github-actions-workflow`` step_runner here.
"""

from __future__ import annotations

import sys
import time
import uuid
from typing import Any, Dict, List, Optional

from yoke_core.domain.deploy_pipeline_gates import _check_ci_gate
from yoke_core.domain.deploy_pipeline_github_workflow_bindings import (
    resolve_declared_input_bindings,
)
from yoke_core.domain.deploy_pipeline_github_workflow_lineage import (
    resolve_publish_sha as _lineage_resolve_publish_sha,
    resolve_release_lineage_sha as _lineage_resolve_release_lineage_sha,
    verify_release_sha_in_checkout as _lineage_verify_release_sha_in_checkout,
)
from yoke_core.domain.deploy_pipeline_github_workflow_reconciliation import (
    _WorkflowReconciliationError,
    _dispatch_correlation_input,
    _find_existing_workflow_run as _reconcile_existing_workflow_run,
    _found_run_id,
    narrate_sha_only_search_skip,
    run_correlated_or_oneshot_trigger,
    trigger_with_binding_collision_retry,
)
from yoke_core.domain.deploy_pipeline_github_workflow_dispatch import (
    trigger_with_recovery_retries,
)
from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
    config_bool as _config_bool,
    resolve_workflow_inputs as _resolve_workflow_inputs,
    workflow_dispatch_request_id as _workflow_dispatch_request_id,
    workflow_inputs as _workflow_inputs,
)
from yoke_core.domain.deploy_pipeline_events import emit_run_event as _emit_run_event
from yoke_core.domain.deploy_pipeline_reporting import (
    _github_actions,
    _poll_github_actions,
    _resolve_script_dir,
    _run_cmd,
)


CORRELATED_WORKFLOW_TIMEOUT_MIN = 120


def _dispatch_github_actions_workflow(
    config: Dict[str, Any],
    *,
    name: str,
    run_id: str,
    member_items: List[str],
    github_repo: str,
    project: str,
    project_repo_path: str,
    timeout_min: int,
    fresh: bool,
    gate_branch: str,
    release_lineage: str,
    product_repo_path: str = "",
    image_tag: str = "",
    environment_name: str = "",
    sd: Optional[str] = None,
) -> tuple[int, str]:
    """Handle github-actions-workflow step_runner.

    Returns ``(exit_code, diagnostic)``.  ``diagnostic`` carries the GitHub
    Actions poll stdout+stderr when the poll declares stage failure so callers
    can surface root cause on ``DeploymentRunStageFailed``.
    """
    sd = sd or _resolve_script_dir()
    workflow = str(config.get("workflow", "") or "")
    if not workflow:
        print(
            "Error: github-actions-workflow stage missing 'workflow'",
            file=sys.stderr,
        )
        return 1, ""
    declared_correlation_input = str(
        config.get("dispatch_correlation_input") or ""
    ).strip()
    correlation_input = _dispatch_correlation_input(config)
    if declared_correlation_input and not correlation_input:
        diagnostic = (
            "github-actions-workflow stage declares unsupported dispatch "
            "correlation input"
        )
        print(f"Error: {diagnostic}", file=sys.stderr)
        return 1, diagnostic
    if not correlation_input:
        print(
            "  Legacy workflow stage has no dispatch correlation input; "
            "using one-shot dispatch without durable response-loss recovery"
        )
    raw_workflow_inputs = _workflow_inputs(config)
    # The ref names which branch of the DEPLOY repo (github_repo) to run the
    # workflow file from, not a product branch — a split deploy/product repo
    # has no gate_branch on the deploy side, so the workflow ref defaults to
    # the deploy repo's own default branch instead. gate_branch stays the
    # separate source-sha/CI-gate branch (a product concept) used below.
    workflow_ref = str(config.get("ref", "") or "main")
    default_timeout_min = (
        max(timeout_min, CORRELATED_WORKFLOW_TIMEOUT_MIN)
        if correlation_input
        else timeout_min
    )
    stage_timeout_min = int(config.get("timeout_min") or default_timeout_min)
    timeout_sec = stage_timeout_min * 60

    if not github_repo:
        print(f"Error: no github_repo configured for project '{project}'", file=sys.stderr)
        return 1, ""

    publish_product = name == "distribution-publish" and product_repo_path
    project_head_sha, lineage_error = _resolve_release_lineage_sha(
        release_lineage, project_repo_path, gate_branch,
    )
    if lineage_error:
        diagnostic = lineage_error
        print(f"Error: {diagnostic}", file=sys.stderr)
        return 1, diagnostic
    wait_for_ci = config.get("wait_for_ci", True)
    if not isinstance(wait_for_ci, bool):
        diagnostic = "github-actions-workflow wait_for_ci must be a boolean"
        print(f"Error: {diagnostic}", file=sys.stderr)
        return 1, diagnostic
    if wait_for_ci:
        ci_passed, ci_msg = _check_ci_gate(
            github_repo, project, timeout_sec, branch=gate_branch,
            head_sha=project_head_sha, sd=sd,
        )
        if ci_msg:
            print(ci_msg, file=sys.stderr if not ci_passed else sys.stdout)
        if not ci_passed:
            return 1, ci_msg or ""
    else:
        print("  CI gate: skipped by this deployment-flow stage")

    head_sha = project_head_sha
    if publish_product:
        head_sha, sha_error = _resolve_publish_sha(
            product_repo_path,
            gate_branch,
            image_tag=image_tag,
        )
        if sha_error:
            print(f"Error: {sha_error}", file=sys.stderr)
            return 1, sha_error

    # Declared external input bindings (e.g. a hosted consumer's trunk sha)
    # resolve before the reconciliation block below, which reads
    # workflow_inputs' truthiness. A `--fresh` retrigger mints its own
    # request id (nothing durable to recover yet); every other call
    # recovers a prior bound pair before resolving fresh.
    input_bindings = config.get("input_bindings") or {}
    bound_inputs: Dict[str, str] = {}
    binding_request_id = (
        _workflow_dispatch_request_id(project, run_id, name)
        if correlation_input and not fresh
        else ""
    )
    if input_bindings:
        bound_inputs, binding_error = resolve_declared_input_bindings(
            input_bindings, request_id=binding_request_id,
        )
        if binding_error:
            print(f"Error: {binding_error}", file=sys.stderr)
            return 1, binding_error

    workflow_inputs = _resolve_workflow_inputs(
        raw_workflow_inputs, head_sha=head_sha, run_id=run_id,
        target_environment=environment_name, bound=bound_inputs,
    )

    ga_run_id = ""
    already_complete = False
    retrigger_scope = ""
    reconcile_by_head_sha = _config_bool(
        config.get("reconcile_by_head_sha", True)
    )
    if fresh:
        print("  --fresh: skipping existing-run search, will trigger new run")
        # One explicit --fresh invocation is one intentional retrigger. Keep
        # the scope stable for every transport retry inside this invocation,
        # while a later --fresh invocation gets a genuinely new dispatch.
        retrigger_scope = f"fresh:{uuid.uuid4().hex}"
    elif not reconcile_by_head_sha:
        narrate_sha_only_search_skip(reconcile_disabled=True)
    elif workflow_inputs:
        narrate_sha_only_search_skip(reconcile_disabled=False)
    elif head_sha:
        try:
            ga_run_id, already_complete, retrigger_scope = (
                _find_existing_workflow_run(
                    github_repo, workflow, head_sha, project=project, sd=sd
                )
            )
        except _WorkflowReconciliationError as exc:
            diagnostic = str(exc)
            print(f"Error: {diagnostic}", file=sys.stderr)
            return 1, diagnostic

    if not ga_run_id and not already_complete:
        def _trigger(inputs: Dict[str, str]) -> tuple[Any, str, Optional[bool]]:
            return run_correlated_or_oneshot_trigger(
                github_actions=_github_actions,
                trigger_with_retries=trigger_with_recovery_retries,
                github_repo=github_repo,
                workflow=workflow,
                workflow_ref=workflow_ref,
                workflow_inputs=inputs,
                request_id=(
                    _workflow_dispatch_request_id(
                        project, run_id, name, retrigger_scope=retrigger_scope,
                    )
                    if correlation_input
                    else ""
                ),
                correlation_input=correlation_input,
                project=project,
                sd=sd,
                timeout_sec=timeout_sec,
            )

        r, ga_run_id, _dispatched, workflow_inputs, binding_error = (
            trigger_with_binding_collision_retry(
                _trigger, workflow_inputs,
                input_bindings=input_bindings,
                binding_request_id=binding_request_id,
                resolve_bindings=resolve_declared_input_bindings,
                resolve_workflow_inputs=_resolve_workflow_inputs,
                raw_workflow_inputs=raw_workflow_inputs,
                head_sha=head_sha, run_id=run_id,
                target_environment=environment_name,
            )
        )
        if binding_error:
            print(f"Error: {binding_error}", file=sys.stderr)
            return 1, binding_error
        if not ga_run_id or r.returncode != 0:
            if not reconcile_by_head_sha or not head_sha or workflow_inputs:
                diagnostic = (r.stderr or r.stdout or "").strip()
                return 1, diagnostic or f"could not trigger workflow run for '{workflow}'"
            print("  Trigger failed, retrying find-run with backoff...")
            reconciliation_errors: list[str] = []
            for attempt in range(1, 7):
                r = _github_actions(
                    "find-run", github_repo, workflow, head_sha,
                    project=project, sd=sd,
                )
                try:
                    ga_run_id = _found_run_id(r, workflow=workflow, head_sha=head_sha)
                except _WorkflowReconciliationError as exc:
                    reconciliation_errors.append(str(exc))
                    print(
                        f"  Workflow run lookup failed (attempt {attempt}/6): {exc}",
                        file=sys.stderr,
                    )
                    ga_run_id = ""
                if ga_run_id:
                    break
                print(f"  Waiting for workflow run to appear... (attempt {attempt}/6)")
                time.sleep(5)  # Registration is an answer that moves in seconds.
            if not ga_run_id and reconciliation_errors:
                diagnostic = (r.stderr or r.stdout or "").strip()
                return 1, (
                    diagnostic
                    or reconciliation_errors[-1]
                    or f"could not reconcile workflow run for '{workflow}'"
                )

    if already_complete:
        # Reconcile-from-truth: a prior workflow run for the same head_sha
        # already concluded success.  Emit the retroactive completion event
        # with the workflow_run reference so the resume path is observable,
        # and return the already-emitted sentinel so run_pipeline does not
        # double-emit the generic success event.
        print(f"  Reconciled stage '{name}' from prior successful run {ga_run_id}")
        _emit_run_event(
            "DeploymentRunStageCompleted", "completed",
            {
                "run_id": run_id,
                "stage": name,
                "result": "success",
                "reconciled": True,
                "workflow_run": ga_run_id,
                "reason": "prior-run-success",
            },
            member_items=member_items, project=project, sd=sd,
        )
        return -3, ""
    if ga_run_id and ga_run_id != "not_found":
        print(f"  Workflow run ID: {ga_run_id}")
        rc, output = _poll_github_actions(
            github_repo, ga_run_id, timeout_sec, project=project, sd=sd,
        )
        # Carry the poll diagnostic only on failure — success output is noise.
        return rc, (output if rc != 0 else "")

    print(f"Error: could not trigger or find workflow run for '{workflow}'", file=sys.stderr)
    return 1, f"could not trigger or find workflow run for '{workflow}'"


def _resolve_release_lineage_sha(
    release_lineage: str, project_repo_path: str, gate_branch: str,
) -> tuple[str, str]:
    """Thin wrapper passing this module's own patchable `_run_cmd` through
    to `deploy_pipeline_github_workflow_lineage`, which owns the resolution."""
    return _lineage_resolve_release_lineage_sha(
        release_lineage, project_repo_path, gate_branch, run_cmd=_run_cmd,
    )


def _verify_release_sha_in_checkout(
    release_sha: str, project_repo_path: str, gate_branch: str,
) -> str:
    """Thin wrapper — see `deploy_pipeline_github_workflow_lineage`."""
    return _lineage_verify_release_sha_in_checkout(
        release_sha, project_repo_path, gate_branch, run_cmd=_run_cmd,
    )


def _resolve_publish_sha(
    project_repo_path: str, gate_branch: str, *, image_tag: str = "",
) -> tuple[str, str]:
    """Thin wrapper — see `deploy_pipeline_github_workflow_lineage`."""
    return _lineage_resolve_publish_sha(
        project_repo_path, gate_branch, image_tag=image_tag, run_cmd=_run_cmd,
    )


def _find_existing_workflow_run(
    github_repo: str, workflow: str, head_sha: str,
    *, project: str, sd: Optional[str],
) -> tuple[str, bool, str]:
    return _reconcile_existing_workflow_run(
        github_repo, workflow, head_sha,
        project=project,
        sd=sd,
        github_actions=_github_actions,
    )
