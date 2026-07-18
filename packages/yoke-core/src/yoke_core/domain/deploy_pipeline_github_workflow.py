"""github-actions-workflow stage executor — CI gate, trigger, reconcile, poll.

Split from :mod:`yoke_core.domain.deploy_pipeline_executors` so the
dispatch table stays small; the dispatcher delegates the
``github-actions-workflow`` executor here.
"""

from __future__ import annotations

import re
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

from yoke_core.domain.deploy_pipeline_gates import _check_ci_gate
from yoke_core.domain.deploy_pipeline_github_workflow_reconciliation import (
    _WorkflowReconciliationError,
    _dispatch_correlation_input,
    _find_existing_workflow_run as _reconcile_existing_workflow_run,
    _found_run_id,
    _trigger_args,
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
from yoke_core.domain.deploy_pipeline_reporting import (
    _emit_run_event,
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
    sd: Optional[str] = None,
) -> tuple[int, str]:
    """Handle github-actions-workflow executor.

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
    # workflow file from — not a product branch. When the deploy repo and the
    # product repo are the same (legacy), gate_branch happened to exist in both;
    # once they split (operator ops repo holding dispatch-only workflows on its
    # default branch vs. a product repo with its own stage branch), gate_branch
    # is absent from the deploy repo and the dispatch 422s. gate_branch stays
    # the source-sha/CI-gate branch (a product concept) below; the workflow ref
    # defaults to the deploy repo's default branch where the file lives.
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
        release_lineage,
        project_repo_path,
        gate_branch,
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
    workflow_inputs = _resolve_workflow_inputs(
        raw_workflow_inputs, head_sha=head_sha, run_id=run_id,
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
        print("  reconcile_by_head_sha=false: skipping existing-run search")
    elif workflow_inputs:
        print(
            "  Stage inputs present: skipping SHA-only existing-run search, "
            "will trigger workflow_dispatch"
        )
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
        print("  No existing run found, triggering workflow_dispatch...")
        trigger_args = _trigger_args(
            github_repo, workflow, workflow_ref, workflow_inputs,
            request_id=(
                _workflow_dispatch_request_id(
                    project, run_id, name, retrigger_scope=retrigger_scope,
                )
                if correlation_input
                else ""
            ),
            correlation_input=correlation_input,
        )
        if correlation_input:
            r = trigger_with_recovery_retries(
                trigger_args, github_actions=_github_actions, project=project,
                sd=sd, timeout_sec=timeout_sec,
            )
        else:
            r = _github_actions(*trigger_args, project=project, sd=sd)
        ga_run_id = r.stdout.strip()
        if not ga_run_id or r.returncode != 0:
            if not reconcile_by_head_sha or not head_sha or workflow_inputs:
                diagnostic = (r.stderr or r.stdout or "").strip()
                return (
                    1,
                    diagnostic
                    or f"could not trigger workflow run for '{workflow}'",
                )
            print("  Trigger failed, retrying find-run with backoff...")
            reconciliation_errors: list[str] = []
            for attempt in range(1, 7):
                r = _github_actions(
                    "find-run", github_repo, workflow, head_sha,
                    project=project, sd=sd,
                )
                try:
                    ga_run_id = _found_run_id(
                        r,
                        workflow=workflow,
                        head_sha=head_sha,
                    )
                except _WorkflowReconciliationError as exc:
                    reconciliation_errors.append(str(exc))
                    print(
                        "  Workflow run lookup failed while reconciling the "
                        f"dispatch (attempt {attempt}/6): {exc}",
                        file=sys.stderr,
                    )
                    ga_run_id = ""
                if ga_run_id:
                    break
                print(f"  Waiting for workflow run to appear... (attempt {attempt}/6)")
                time.sleep(5)
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
            github_repo, ga_run_id, timeout_sec, name,
            project=project, sd=sd,
        )
        # Carry the poll diagnostic only on failure — success output is noise.
        return rc, (output if rc != 0 else "")

    print(f"Error: could not trigger or find workflow run for '{workflow}'", file=sys.stderr)
    return 1, f"could not trigger or find workflow run for '{workflow}'"


def _resolve_release_lineage_sha(
    release_lineage: str,
    project_repo_path: str,
    gate_branch: str,
) -> tuple[str, str]:
    """Resolve a run's immutable lineage without consulting a branch head.

    Current runs bind directly to a full commit SHA. Historical release runs
    bind to an annotated release tag; for those, use only the remote tag's
    peeled commit. A lightweight tag is refused because it lacks the governed
    annotated-release boundary expected by the hosted release train.
    """
    lineage = release_lineage.strip()
    if not lineage:
        return "", (
            "github-actions-workflow requires the deployment run to carry "
            "an immutable release_lineage commit SHA or annotated release tag"
        )
    if re.fullmatch(r"[0-9a-f]{40}", lineage):
        checkout_error = _verify_release_sha_in_checkout(
            lineage,
            project_repo_path,
            gate_branch,
        )
        if checkout_error:
            return "", checkout_error
        return lineage, ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+~-]{0,127}", lineage):
        return "", (
            "deployment run release_lineage is neither an exact 40-character "
            "lowercase Git commit SHA nor a safe annotated release tag"
        )

    repo = project_repo_path or "."
    peeled_ref = f"refs/tags/{lineage}^{{}}"
    result = _run_cmd(
        [
            "git", "-C", repo, "ls-remote", "origin",
            f"refs/tags/{lineage}", peeled_ref,
        ]
    )
    if result.returncode != 0:
        return "", (
            f"could not resolve annotated release tag '{lineage}' from origin"
        )
    peeled = [
        fields[0]
        for raw_line in result.stdout.splitlines()
        if len(fields := raw_line.split()) == 2
        and fields[1] == peeled_ref
        and re.fullmatch(r"[0-9a-f]{40}", fields[0])
    ]
    if len(set(peeled)) != 1:
        return "", (
            f"release_lineage '{lineage}' does not resolve to exactly one "
            "annotated release-tag commit on origin"
        )
    return peeled[0], ""


def _verify_release_sha_in_checkout(
    release_sha: str,
    project_repo_path: str,
    gate_branch: str,
) -> str:
    """Prove ``release_sha`` is an available commit without following a ref.

    Item-bound run creation separately proves that its selected commit is the
    configured environment branch head.  Execution and resume must remain
    independent of that branch afterward: an environment-level run may select
    any branch, and a saved commit stays authoritative when refs move.
    """
    del gate_branch
    repo = project_repo_path or "."
    commit_ref = f"{release_sha}^{{commit}}"
    present = _run_cmd(["git", "-C", repo, "cat-file", "-e", commit_ref])
    if present.returncode == 0:
        return ""
    fetched = _run_cmd([
        "git", "-C", repo, "fetch", "--quiet", "--no-tags", "origin",
        release_sha,
    ])
    if fetched.returncode == 0:
        present = _run_cmd([
            "git", "-C", repo, "cat-file", "-e", commit_ref,
        ])
    if present.returncode != 0:
        return (
            f"deployment run release_lineage {release_sha} is not a commit "
            "available from the project repository"
        )
    return ""


def _resolve_publish_sha(
    project_repo_path: str,
    gate_branch: str,
    *,
    image_tag: str = "",
) -> tuple[str, str]:
    """Resolve the publish source from an explicit product pin when supplied.

    Unpinned legacy callers retain remote deploy-branch resolution; worktree
    flows without a gate branch use their local HEAD.
    """
    if image_tag:
        from yoke_core.domain.deploy_product_source import (
            DeployProductSourceError,
            resolve_product_commit,
        )

        try:
            return resolve_product_commit(project_repo_path, image_tag), ""
        except DeployProductSourceError as exc:
            return "", str(exc)
    if gate_branch:
        repo = project_repo_path or "."
        result = _run_cmd(
            ["git", "-C", repo, "ls-remote", "origin", f"refs/heads/{gate_branch}"]
        )
        sha = ""
        if result.returncode == 0 and result.stdout.strip():
            sha = result.stdout.split()[0].strip()
        if not sha:
            return "", (
                f"could not resolve the deployed SHA for branch "
                f"'{gate_branch}' on origin — the branch is missing from the "
                f"remote or unreachable; push '{gate_branch}' before publishing"
            )
        return sha, ""
    command = ["git", "rev-parse", "HEAD"]
    if project_repo_path:
        command[1:1] = ["-C", project_repo_path]
    sha = _run_cmd(command).stdout.strip()
    return sha, ""


def _find_existing_workflow_run(
    github_repo: str,
    workflow: str,
    head_sha: str,
    *,
    project: str,
    sd: Optional[str],
) -> tuple[str, bool, str]:
    return _reconcile_existing_workflow_run(
        github_repo,
        workflow,
        head_sha,
        project=project,
        sd=sd,
        github_actions=_github_actions,
    )
