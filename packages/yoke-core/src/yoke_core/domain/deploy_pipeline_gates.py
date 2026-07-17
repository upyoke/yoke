"""Deployment pipeline gates — gate-branch resolution, merged gate, CI gate.

A flow's gate branch is the target env's declared long-lived deploy branch
(``environments.settings.git.branch``: main<->prod, stage<->stage); flows
without a target env, and envs that declare no branch (ephemerals), gate
against the project base branch. The merged gate and the CI gate both
verify against that one resolved branch.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

from yoke_core.domain import json_helper
from yoke_core.domain.deploy_pipeline_reporting import (
    _github_actions,
    _run_cmd,
    _yoke_db,
)
from yoke_core.domain.project_renderer_settings import project_ci_workflow_file


def resolve_flow_gate_branch(
    project: str, target_env: str, repo_root: str = "",
) -> str:
    """Resolve the branch a flow's merged gate verifies against.

    Returns ``""`` for the ephemeral tier (``target_env="ephemeral"``):
    preview flows deploy unmerged worktree branches by design, so no
    merged/CI gate branch exists for them. ``repo_root`` is the project
    checkout whose scope-first ``base_branch`` stance governs the
    fallback when no environment declares a branch.
    """
    from yoke_core.domain.ephemeral_substrate import EPHEMERAL_TARGET_ENV

    if target_env == EPHEMERAL_TARGET_ENV:
        return ""
    if project and target_env:
        from yoke_core.domain.deploy_environment_settings import (
            declared_env_branch,
        )

        declared = declared_env_branch(project, target_env)
        if declared:
            return declared
    from yoke_core.domain import project_settings

    return project_settings.get_project_str(repo_root, "base_branch")


def _resolve_and_verify_branch(
    member_items: List[str],
    project_repo_path: str,
    *,
    target_branch: str,
    sd: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """Resolve the first member item's branch; verify it landed on *target_branch*.

    ``target_branch`` is the flow's gate branch from
    :func:`resolve_flow_gate_branch`. Item-less runs (environment-level
    deploys) have no branch to verify and skip straight through.
    Returns ``(ok, first_item, branch)``.
    """
    if not member_items:
        return True, "", ""
    first_item = member_items[0]
    branch = _yoke_db("items", "get", f"YOK-{first_item}", "worktree", sd=sd)
    if not target_branch:
        # Ephemeral tier: the deploy subject IS the unmerged worktree
        # branch, so there is no gate branch to verify against.
        print(
            f"Ephemeral tier: deploying worktree branch '{branch}' "
            "without a merged gate"
        )
        return True, first_item, branch
    check_repo = project_repo_path or "."
    if not os.path.isdir(os.path.join(check_repo, ".git")):
        r = _run_cmd(["git", "rev-parse", "--show-toplevel"])
        check_repo = r.stdout.strip() or "."
    ok, msg = _verify_branch_merged(branch, first_item, check_repo, target_branch)
    if msg:
        print(msg, file=sys.stderr if not ok else sys.stdout)
    return ok, first_item, branch


def _verify_branch_merged(
    branch: str,
    first_item: str,
    repo_path: str,
    target_branch: str,
) -> Tuple[bool, str]:
    """Check that branch commits exist on *target_branch*.

    Returns (ok, message).  ``ok=True`` means proceed.
    """
    if not branch or branch == "null":
        return True, (
            f"Warning: YOK-{first_item} has no branch set — cannot verify "
            f"commits are on {target_branch}. Proceeding."
        )

    # Check if branch exists
    r = _run_cmd(["git", "-C", repo_path, "rev-parse", "--verify", branch])
    if r.returncode != 0:
        # Branch doesn't exist — check for squash-merge evidence
        r2 = _run_cmd(["git", "-C", repo_path, "log", "--oneline", f"--grep=YOK-{first_item}", target_branch])
        merge_found = r2.stdout.strip().split("\n")[0] if r2.stdout.strip() else ""
        if not merge_found:
            return True, (
                f"Warning: YOK-{first_item} branch '{branch}' not found and "
                f"no merge commit referencing YOK-{first_item} found on "
                f"{target_branch}. Proceeding with caution."
            )
        return True, ""

    # Branch exists — check ancestry
    r = _run_cmd(["git", "-C", repo_path, "merge-base", "--is-ancestor", branch, target_branch])
    if r.returncode == 0:
        return True, ""

    # Not ancestor — check for squash-merge evidence
    r2 = _run_cmd(["git", "-C", repo_path, "log", "--oneline", f"--grep=YOK-{first_item}", target_branch])
    squash_evidence = r2.stdout.strip().split("\n")[0] if r2.stdout.strip() else ""
    if squash_evidence:
        return True, (
            f"Squash-merge detected for YOK-{first_item} "
            f"(branch exists but is not ancestor of {target_branch}). Proceeding."
        )

    return False, (
        f"Blocked: Cannot deploy — branch {branch} commits are not on {target_branch}.\n"
        f"The deployment pipeline requires the item's code to be on the gate branch\n"
        f"(the target env's declared deploy branch). Push and merge the branch into\n"
        f"{target_branch} first, then re-run the pipeline."
    )


def _check_ci_gate(
    github_repo: str,
    project: str,
    timeout_sec: int,
    *,
    branch: str,
    head_sha: str = "",
    sd: Optional[str] = None,
) -> Tuple[bool, str]:
    """Check CI for the exact release commit before deploying.

    ``branch`` is the gate branch from :func:`resolve_flow_gate_branch`.
    Returns (passed, message).
    """
    ci_workflow = project_ci_workflow_file(project)

    if not ci_workflow:
        return (
            True,
            f"  CI gate: no ci_workflow_file capability configured for project '{project}' — skipping",
        )

    subject = f"{branch}@{head_sha[:12]}" if head_sha else branch
    print(f"  CI gate: checking {ci_workflow} on {subject} for {github_repo}...")

    check_args = [
        "check-ci", github_repo, ci_workflow,
        "--branch", branch,
    ]
    if head_sha:
        check_args.extend(["--head-sha", head_sha])
    check_args.extend(["--wait", "--timeout", str(timeout_sec), "--json"])
    r = _github_actions(
        *check_args,
        project=project, sd=sd, timeout=timeout_sec + 30,
    )
    output = "\n".join(
        part.strip() for part in (r.stdout, r.stderr) if part.strip()
    )
    envelope = _function_response_envelope(output)

    if envelope is None:
        detail = f"\n\nGitHub Actions detail:\n{output}" if output else ""
        return False, (
            "\nBLOCKED: Cannot deploy — the GitHub Actions adapter omitted "
            f"its required typed response (exit {r.returncode}).{detail}\n\n"
            "The release fails closed because non-JSON or truncated output "
            "cannot prove a CI conclusion.\n"
        )

    if envelope.get("success") is not True:
        error = envelope.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "unknown_error")
            detail = str(error.get("message") or "").strip()
            failure = f"{code}: {detail}" if detail else code
        else:
            failure = "unknown_error"
        return False, (
            "\nBLOCKED: Cannot deploy — CI could not be verified; "
            f"the GitHub Actions adapter returned {failure}.\n\n"
            "This is an authorization or transport failure, not a "
            "failing test conclusion.\n"
        )

    result = envelope.get("result")
    state = str(result.get("state") or "") if isinstance(result, dict) else ""
    if state == "passed":
        return True, f"  CI gate: {subject} CI passed"
    if state == "failed":
        return False, _failed_ci_message(branch)
    if state == "timeout":
        return False, _timed_out_ci_message(branch, timeout_sec)
    if state == "no_runs":
        if head_sha:
            return False, (
                "\nBLOCKED: Cannot deploy — no CI run exists for exact "
                f"release commit {head_sha} on {branch}.\n"
            )
        return True, f"  CI gate: no CI runs found on {branch} — skipping"
    return False, (
        "\nBLOCKED: Cannot deploy — the GitHub Actions wait adapter "
        f"returned non-terminal state {state or '<empty>'!r}.\n\n"
        "The release remains blocked without treating in-progress CI as "
        "a test failure.\n"
    )


def _function_response_envelope(output: str) -> Optional[dict]:
    """Return the typed function response embedded in adapter output."""
    for raw_line in reversed(output.splitlines()):
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json_helper.loads_text(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "success" in parsed:
            return parsed
    return None


def _failed_ci_message(branch: str) -> str:
    return (
        f"\nBLOCKED: Cannot deploy — {branch} branch CI has failed.\n\n"
        "Remediation:\n"
        f"  1. Fix the failing CI on {branch}\n"
        "  2. Re-run the deployment pipeline\n"
    )


def _timed_out_ci_message(branch: str, timeout_sec: int) -> str:
    return (
        f"\nBLOCKED: Cannot deploy — {branch} branch CI timed out "
        f"({timeout_sec}s).\n\n"
        "Remediation:\n"
        "  1. Wait for CI to complete, then re-run the deployment pipeline\n"
        "  2. Or increase --timeout if the CI workflow normally takes longer\n"
    )
