"""Deployment pipeline gates — gate-branch resolution, merged gate, CI gate.

A flow's gate branch is the target env's declared long-lived deploy branch
(``environments.settings.git.branch``: main<->prod, stage<->stage); flows
without a target env, and envs that declare no branch, gate against the
project base branch. The merged gate verifies containment in the run’s
frozen source commit.
The CI gate uses the resolved branch and exact source commit; ephemeral
candidates skip merged verification.
"""

from __future__ import annotations

from yoke_core.domain.public_item_target import public_item_target

import os
import sys
from typing import List, Optional, Tuple

from yoke_contracts.designed_wait import announce_designed_wait
from yoke_core.domain import json_helper
from yoke_core.domain.deploy_pipeline_reporting import (
    _github_actions,
    _run_cmd,
)
from yoke_core.domain import deploy_pipeline_ci_recovery as ci_recovery
from yoke_core.domain.project_renderer_settings import project_ci_workflow_file


def resolve_flow_gate_branch(
    project: str,
    target_tier: str,
    environment: str,
    repo_root: str = "",
) -> str:
    """Resolve the branch a flow's merged gate verifies against.

    Returns ``""`` for the ephemeral tier: preview flows deploy unmerged
    worktree branches by design, so no gate branch exists for them and
    the CI gate falls back to verifying the exact release commit.
    ``repo_root`` is the project checkout whose scope-first
    ``base_branch`` stance governs the fallback when the referenced
    environment declares no branch.
    """
    from yoke_contracts.deployment_flow_target_tier import (
        TARGET_TIER_EPHEMERAL,
    )

    if target_tier == TARGET_TIER_EPHEMERAL:
        return ""
    if project and environment:
        from yoke_core.domain.deploy_environment_settings import (
            declared_env_branch,
        )

        declared = declared_env_branch(project, environment)
        if declared:
            return declared
    from yoke_core.domain import project_settings

    return project_settings.get_project_str(repo_root, "base_branch")


def _resolve_and_verify_branch(
    member_items: List[str],
    project_repo_path: str,
    *,
    target_branch: str,
    source_sha: str,
    first_branch: str = "",
    first_item_label: str = "",
    sd: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """Resolve the first member branch; verify containment in the frozen source.

    ``target_branch`` is the flow's gate branch from
    :func:`resolve_flow_gate_branch`. Item-less runs (environment-level
    deploys) have no branch to verify and skip straight through.
    Returns ``(ok, first_item, branch)``.
    """
    if not member_items:
        return True, "", ""
    first_item = member_items[0]
    branch = first_branch
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
    ok, msg = _verify_branch_merged(
        branch,
        first_item,
        check_repo,
        source_sha,
        public_ref=first_item_label,
    )
    if msg:
        print(msg, file=sys.stderr if not ok else sys.stdout)
    return ok, first_item, branch


def _verify_branch_merged(
    branch: str,
    first_item: str,
    repo_path: str,
    source_sha: str,
    *,
    public_ref: str = "",
) -> Tuple[bool, str]:
    """Check branch ancestry or squash evidence in the frozen source commit.

    Returns (ok, message).  ``ok=True`` means proceed.
    """
    public_ref = public_ref or str(public_item_target(first_item).public_ref)
    grep_pattern = public_ref
    if (
        len(source_sha) != 40
        or _run_cmd(
            ["git", "-C", repo_path, "cat-file", "-e", f"{source_sha}^{{commit}}"]
        ).returncode
        != 0
    ):
        return False, (
            f"Blocked (release_source_unavailable): frozen source {source_sha!r} "
            "is not a readable full commit. Restore the run's source commit in "
            "the project checkout, or repair its release lineage, then retry."
        )
    if not branch or branch == "null":
        return True, (
            f"Warning: {public_ref} has no branch set — cannot verify "
            f"commits are on {source_sha}. Proceeding."
        )

    # Check if branch exists
    r = _run_cmd(["git", "-C", repo_path, "rev-parse", "--verify", branch])
    if r.returncode != 0:
        # Branch doesn't exist — check for squash-merge evidence
        r2 = _run_cmd(
            [
                "git",
                "-C",
                repo_path,
                "log",
                "--oneline",
                "-E",
                f"--grep={grep_pattern}",
                source_sha,
            ]
        )
        merge_found = r2.stdout.strip().split("\n")[0] if r2.stdout.strip() else ""
        if not merge_found:
            return True, (
                f"Warning: {public_ref} branch '{branch}' not found and "
                f"no merge commit referencing {public_ref} found on "
                f"{source_sha}. Proceeding with caution."
            )
        return True, ""

    # Branch exists — check ancestry
    r = _run_cmd(
        ["git", "-C", repo_path, "merge-base", "--is-ancestor", branch, source_sha]
    )
    if r.returncode == 0:
        return True, ""

    # Not ancestor — check for squash-merge evidence
    r2 = _run_cmd(
        [
            "git",
            "-C",
            repo_path,
            "log",
            "--oneline",
            "-E",
            f"--grep={grep_pattern}",
            source_sha,
        ]
    )
    squash_evidence = r2.stdout.strip().split("\n")[0] if r2.stdout.strip() else ""
    if squash_evidence:
        return True, (
            f"Squash-merge detected for {public_ref} "
            f"(branch exists but is not ancestor of {source_sha}). Proceeding."
        )

    return False, (
        f"Blocked (release_member_not_in_source): branch {branch} commits are not "
        f"in frozen source {source_sha}.\n"
        "Merge the member into the declared deploy branch and compose a new run "
        "whose frozen source contains it; retrying this source cannot include it."
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

    ``branch`` is the gate branch from :func:`resolve_flow_gate_branch`,
    empty for an ephemeral candidate that has no branch of its own; that
    candidate is verified by ``head_sha`` alone rather than through a
    branch filter nothing can match. Returns (passed, message).
    """
    ci_workflow = project_ci_workflow_file(project)

    if not ci_workflow:
        return (
            True,
            f"  CI gate: no ci_workflow_file capability configured for project '{project}' — skipping",
        )
    if not branch and not head_sha:
        return False, ci_recovery.unverifiable_ci_target_message(
            github_repo=github_repo,
            workflow=ci_workflow,
        )

    subject = ci_recovery.ci_gate_subject(branch, head_sha)
    announce_designed_wait(
        f"CI gate {ci_workflow} on {subject} for {github_repo}",
        max_wait_seconds=timeout_sec,
        write=print,
    )

    # --branch is always sent, empty included: the adapter defaults an
    # absent flag to main, which would filter a branchless candidate
    # against a branch it was never released from.
    check_args = ["check-ci", github_repo, ci_workflow, "--branch", branch]
    if head_sha:
        check_args.extend(["--head-sha", head_sha])
    check_args.extend(["--wait", "--timeout", str(timeout_sec), "--json"])
    r = _github_actions(
        *check_args,
        project=project,
        sd=sd,
        timeout=timeout_sec + 30,
    )
    output = "\n".join(part.strip() for part in (r.stdout, r.stderr) if part.strip())
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
            code = "unknown_error"
            failure = "unknown_error"
        return False, ci_recovery.ci_adapter_failure_message(
            code,
            failure,
            workflow=ci_workflow,
            repo=github_repo,
        )

    result = envelope.get("result")
    state = str(result.get("state") or "") if isinstance(result, dict) else ""
    if state == "passed":
        return True, f"  CI gate: {subject} CI passed"
    if state == "failed":
        return False, ci_recovery.failed_ci_message(subject)
    if state == "no_verdict":
        conclusion = (
            str(result.get("conclusion") or "") if isinstance(result, dict) else ""
        )
        return False, ci_recovery.no_verdict_ci_message(
            subject=subject,
            conclusion=conclusion,
            project=project,
            head_sha=head_sha,
        )
    if state == "timeout":
        return False, ci_recovery.timed_out_ci_message(subject, timeout_sec)
    if state == "no_runs":
        if head_sha and not branch:
            return False, ci_recovery.branchless_dispatch_message(
                github_repo=github_repo,
                workflow=ci_workflow,
                head_sha=head_sha,
            )
        if head_sha:
            return False, ci_recovery.missing_ci_run_message(
                github_repo=github_repo,
                project=project,
                workflow=ci_workflow,
                branch=branch,
                head_sha=head_sha,
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
