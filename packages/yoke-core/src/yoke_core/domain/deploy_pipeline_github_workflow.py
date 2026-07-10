"""github-actions-workflow stage executor — CI gate, trigger, reconcile, poll.

Split from :mod:`yoke_core.domain.deploy_pipeline_executors` so the
dispatch table stays small; the dispatcher delegates the
``github-actions-workflow`` executor here.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Optional

from yoke_core.domain.deploy_pipeline_gates import _check_ci_gate
from yoke_core.domain.deploy_pipeline_reporting import (
    _emit_run_event,
    _github_actions,
    _poll_github_actions,
    _resolve_script_dir,
    _run_cmd,
)


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
    stage_timeout_min = int(config.get("timeout_min") or timeout_min)
    timeout_sec = stage_timeout_min * 60

    if not github_repo:
        print(f"Error: no github_repo configured for project '{project}'", file=sys.stderr)
        return 1, ""

    ci_passed, ci_msg = _check_ci_gate(
        github_repo, project, timeout_sec, branch=gate_branch, sd=sd
    )
    if ci_msg:
        print(ci_msg, file=sys.stderr if not ci_passed else sys.stdout)
    if not ci_passed:
        return 1, ci_msg or ""

    publish_product = name == "distribution-publish" and product_repo_path
    head_sha, sha_error = _resolve_publish_sha(
        product_repo_path if publish_product else project_repo_path,
        gate_branch,
        image_tag=image_tag if publish_product else "",
    )
    if sha_error:
        print(f"Error: {sha_error}", file=sys.stderr)
        return 1, sha_error
    workflow_inputs = _resolve_workflow_inputs(
        raw_workflow_inputs, head_sha=head_sha,
    )

    ga_run_id = ""
    already_complete = False
    reconcile_by_head_sha = _config_bool(
        config.get("reconcile_by_head_sha", True)
    )
    if fresh:
        print("  --fresh: skipping existing-run search, will trigger new run")
    elif not reconcile_by_head_sha:
        print("  reconcile_by_head_sha=false: skipping existing-run search")
    elif workflow_inputs:
        print(
            "  Stage inputs present: skipping SHA-only existing-run search, "
            "will trigger workflow_dispatch"
        )
    elif head_sha:
        ga_run_id, already_complete = _find_existing_workflow_run(
            github_repo, workflow, head_sha, project=project, sd=sd
        )

    if not ga_run_id and not already_complete:
        print("  No existing run found, triggering workflow_dispatch...")
        r = _github_actions(
            *_trigger_args(github_repo, workflow, workflow_ref, workflow_inputs),
            project=project, sd=sd,
        )
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
            for attempt in range(1, 7):
                r = _github_actions(
                    "find-run", github_repo, workflow, head_sha,
                    project=project, sd=sd,
                )
                ga_run_id = r.stdout.strip()
                if ga_run_id and ga_run_id != "not_found":
                    break
                print(f"  Waiting for workflow run to appear... (attempt {attempt}/6)")
                time.sleep(5)

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


def _workflow_inputs(config: Dict[str, Any]) -> Dict[str, str]:
    raw = config.get("inputs", {})
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {
            str(key): str(value)
            for key, value in raw.items()
            if value is not None
        }
    if isinstance(raw, list):
        result: Dict[str, str] = {}
        for item in raw:
            key, sep, value = str(item).partition("=")
            if sep and key:
                result[key] = value
        return result
    return {}


def _resolve_workflow_inputs(
    workflow_inputs: Dict[str, str],
    *,
    head_sha: str,
) -> Dict[str, str]:
    replacements = {
        "{head_sha}": head_sha,
        "$head_sha": head_sha,
        "${head_sha}": head_sha,
    }
    return {
        key: replacements.get(value, value)
        for key, value in workflow_inputs.items()
    }


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


def _config_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _trigger_args(
    github_repo: str,
    workflow: str,
    workflow_ref: str,
    workflow_inputs: Dict[str, str],
) -> list[str]:
    args = ["trigger", github_repo, workflow, "--ref", workflow_ref]
    for key in sorted(workflow_inputs):
        args.extend(["--input", f"{key}={workflow_inputs[key]}"])
    return args


def _find_existing_workflow_run(
    github_repo: str,
    workflow: str,
    head_sha: str,
    *,
    project: str,
    sd: Optional[str],
) -> tuple[str, bool]:
    r = _github_actions(
        "find-run", github_repo, workflow, head_sha, project=project, sd=sd,
    )
    ga_run_id = r.stdout.strip()
    if not ga_run_id or ga_run_id == "not_found":
        return "", False

    print(f"  Found existing run {ga_run_id} for {workflow} @ {head_sha[:8]}")
    r2 = _github_actions(
        "jobs-count", github_repo, ga_run_id, project=project, sd=sd,
    )
    job_count = r2.stdout.strip() or "0"
    if job_count == "0":
        print(f"  Existing run {ga_run_id} has zero jobs — triggering fresh run")
        return "", False

    r3 = _github_actions(
        "poll", github_repo, ga_run_id, project=project, sd=sd,
    )
    status = r3.stdout.strip()
    if r3.returncode == 0 and status == "success":
        print("  Run already completed successfully — skipping deploy trigger")
        return ga_run_id, True
    if status.startswith("failed:"):
        print(f"  Existing run {ga_run_id} failed — treating as stale, auto-triggering fresh run")
        return "", False

    print(f"  Existing run status: {status} — attaching to it")
    return ga_run_id, False
