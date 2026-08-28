"""Automatic CI dispatch for exact-commit deployment gates."""

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
    "ci_gate_dispatch_request_id",
    "dispatch_missing_ci_run",
    "missing_ci_run_message",
    "recover_missing_ci_gate",
]
