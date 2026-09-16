"""Exact-commit CI gate targeting, refusals, and automatic dispatch.

A gate verifies one release commit. It reaches that commit through a
branch when the flow has one, and through the commit alone when the
candidate is frozen without a branch of its own. Dispatch is the branch
path only: GitHub runs a workflow from a branch or tag ref, never from a
bare commit, so a branchless gate with no run to read refuses here rather
than starting a run against a revision nobody asked to release.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Optional

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.domain.deploy_pipeline_github_workflow_dispatch import (
    trigger_with_recovery_retries,
)
from yoke_core.domain.deploy_pipeline_github_workflow_reconciliation import (
    _trigger_args,
)


def ci_gate_subject(branch: str, head_sha: str) -> str:
    """Name the verification target for gate output and refusals."""
    short_sha = head_sha[:12]
    if branch and short_sha:
        return f"{branch}@{short_sha}"
    return short_sha or branch


def unverifiable_ci_target_message(*, github_repo: str, workflow: str) -> str:
    """Refuse a gate that named neither a branch nor a release commit."""
    return (
        "\nBLOCKED: Cannot deploy — CI cannot be verified: this run named "
        f"neither a gate branch nor a release commit for declared workflow "
        f"{workflow} in {github_repo}.\n\n"
        "The newest run of a workflow proves nothing about an unnamed "
        "commit, so the gate refuses rather than reading one.\n\n"
        "Recovery:\n"
        "  1. Give the run a release lineage so the gate resolves an exact "
        "commit\n"
        "  2. Or declare the target environment's deploy branch "
        "(environments.settings.git.branch)\n"
    )


def branchless_dispatch_message(
    *, github_repo: str, workflow: str, head_sha: str,
) -> str:
    """Refuse dispatch for a frozen commit that has no branch to run from."""
    return (
        "\nBLOCKED: Cannot deploy — no CI run exists for exact release "
        f"commit {head_sha} in declared workflow {workflow}, and this run "
        "has no gate branch to dispatch one from.\n\n"
        "GitHub runs a workflow from a branch or tag, never from a bare "
        "commit, so dispatching here would verify a different revision "
        "than the frozen one.\n\n"
        "Recovery:\n"
        f"  1. Point a branch or tag at {head_sha} in {github_repo}, push "
        f"it, then re-run the deployment\n"
        f"  2. Or run {workflow} against {head_sha} by hand and re-run the "
        "deployment, which reads that run by exact commit\n"
    )


def ci_gate_dispatch_request_id(
    project: str,
    github_repo: str,
    workflow: str,
    head_sha: str,
) -> str:
    """Return one bounded idempotency key for an exact verification target."""
    target = "\n".join((project, github_repo, workflow, head_sha))
    digest = hashlib.sha256(target.encode("utf-8")).hexdigest()
    return f"ci-gate:{digest}"


def dispatch_missing_ci_run(
    *,
    github_actions: Callable[..., Any],
    github_repo: str,
    project: str,
    workflow: str,
    branch: str,
    head_sha: str,
    timeout_sec: int,
    sd: Optional[str],
) -> tuple[str, str]:
    """Dispatch or recover the declared CI run; return ``(run_id, error)``."""
    args = _trigger_args(
        github_repo,
        workflow,
        branch,
        {},
        request_id=ci_gate_dispatch_request_id(
            project,
            github_repo,
            workflow,
            head_sha,
        ),
        correlation_input=WORKFLOW_DISPATCH_CORRELATION_INPUT,
    )
    result = trigger_with_recovery_retries(
        args,
        github_actions=github_actions,
        project=project,
        sd=sd,
        timeout_sec=timeout_sec,
    )
    run_id = (result.stdout or "").strip()
    if result.returncode == 0 and run_id:
        return run_id, ""
    detail = (result.stderr or result.stdout or "").strip()
    return "", detail or "the GitHub Actions adapter returned no run id"


def missing_ci_run_message(
    *,
    github_repo: str,
    workflow: str,
    branch: str,
    head_sha: str,
    dispatched_run_id: str = "",
    dispatch_error: str = "",
) -> str:
    """Teach the exact missing-run condition and its recovery."""
    dispatch_fact = ""
    if dispatched_run_id:
        dispatch_fact = (
            f"\nAutomatic dispatch returned run {dispatched_run_id}, but that run "
            "did not register for the required commit."
        )
    elif dispatch_error:
        dispatch_fact = f"\nAutomatic dispatch failed: {dispatch_error}"
    return (
        "\nBLOCKED: Cannot deploy — no CI run exists for exact release commit "
        f"{head_sha} on {branch} in declared workflow {workflow}."
        f"{dispatch_fact}\n\n"
        "Recovery:\n"
        f"  1. Confirm {github_repo}@{branch} still points at {head_sha}\n"
        f"  2. Confirm {workflow} accepts workflow_dispatch with the "
        f"{WORKFLOW_DISPATCH_CORRELATION_INPUT} input\n"
        "  3. Re-run the deployment; the gate dispatches and waits for that "
        "exact commit automatically\n"
    )


def recover_missing_ci_gate(
    *,
    github_actions: Callable[..., Any],
    recheck: Callable[[str], tuple[bool, str]],
    github_repo: str,
    project: str,
    workflow: str,
    branch: str,
    head_sha: str,
    timeout_sec: int,
    sd: Optional[str],
    dispatched_run_id: str,
) -> tuple[bool, str]:
    """Dispatch once, then ask the gate to verify the same exact commit."""
    if not branch:
        return False, branchless_dispatch_message(
            github_repo=github_repo, workflow=workflow, head_sha=head_sha,
        )
    if dispatched_run_id:
        return False, missing_ci_run_message(
            github_repo=github_repo,
            workflow=workflow,
            branch=branch,
            head_sha=head_sha,
            dispatched_run_id=dispatched_run_id,
        )
    run_id, error = dispatch_missing_ci_run(
        github_actions=github_actions,
        github_repo=github_repo,
        project=project,
        workflow=workflow,
        branch=branch,
        head_sha=head_sha,
        timeout_sec=timeout_sec,
        sd=sd,
    )
    if run_id:
        return recheck(run_id)
    return False, missing_ci_run_message(
        github_repo=github_repo,
        workflow=workflow,
        branch=branch,
        head_sha=head_sha,
        dispatch_error=error,
    )


__all__ = [
    "branchless_dispatch_message",
    "ci_gate_dispatch_request_id",
    "ci_gate_subject",
    "dispatch_missing_ci_run",
    "missing_ci_run_message",
    "recover_missing_ci_gate",
    "unverifiable_ci_target_message",
]
