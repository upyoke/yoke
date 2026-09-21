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


_QUEUE_REF_PREFIX = "gh-readonly-queue/"


def failed_ci_message(subject: str) -> str:
    """Refuse a deploy whose declared CI run concluded failure."""
    return (
        f"\nBLOCKED: Cannot deploy — CI has failed for {subject}.\n\n"
        "Remediation:\n"
        f"  1. Fix the failing CI on {subject}\n"
        "  2. Re-run the deployment pipeline\n"
    )


def timed_out_ci_message(subject: str, timeout_sec: int) -> str:
    """Refuse a deploy whose CI wait budget ended before a conclusion."""
    return (
        f"\nBLOCKED: Cannot deploy — CI timed out for {subject} "
        f"({timeout_sec}s).\n\n"
        "Remediation:\n"
        "  1. Wait for CI to complete, then re-run the deployment pipeline\n"
        "  2. Or increase --timeout if the CI workflow normally takes longer\n"
    )


def merge_queue_same_tree_note(runs: list[Any]) -> str:
    """Name a same-tree merge-queue conclusion when the listing has one."""
    queue_runs = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        event = str(run.get("event") or "")
        head_branch = str(run.get("head_branch") or "")
        if event != "merge_group" and not head_branch.startswith(_QUEUE_REF_PREFIX):
            continue
        queue_runs.append(run)
    if not queue_runs:
        return ""
    chosen = next(
        (
            run for run in queue_runs
            if str(run.get("conclusion") or "") == "success"
        ),
        queue_runs[0],
    )
    conclusion = str(chosen.get("conclusion") or "").strip() or "none"
    name = str(chosen.get("name") or "workflow")
    loc = str(chosen.get("head_branch") or chosen.get("event") or "merge queue")
    return (
        f"A merge-queue run of {name} on {loc} for this identical tree "
        f"already concluded {conclusion}; that does not satisfy this gate.\n\n"
    )


def no_verdict_ci_message(
    *,
    subject: str,
    conclusion: str,
    project: str = "",
    head_sha: str = "",
    sibling_runs: list[Any] | None = None,
) -> str:
    """Refuse a deploy whose CI run completed without a pass or fail."""
    named = (conclusion or "").strip() or "empty"
    runs = sibling_runs
    if runs is None and project and head_sha:
        from yoke_core.domain.github_actions_commit_runs_read import (
            CommitRunAuthorityError,
            matching_runs,
        )

        try:
            runs = matching_runs(project, head_sha, "")
        except CommitRunAuthorityError:
            runs = []
    queue_note = merge_queue_same_tree_note(runs or [])
    return (
        f"\nBLOCKED: Cannot deploy — CI has no verdict for {subject} "
        f"(conclusion {named}).\n\n"
        "A cancelled, skipped, or otherwise unfinished run is not a test "
        "failure.\n\n"
        f"{queue_note}"
        "Recovery:\n"
        "  1. Obtain a CI verdict for this exact commit (re-run the declared "
        "workflow on this SHA)\n"
        "  2. Re-run the deployment pipeline\n"
    )


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
        "Recovery, in order — a ref alone starts no run, so stopping "
        "early returns to this same refusal:\n"
        f"  1. Create or move a branch or tag in {github_repo} so it "
        f"resolves to {head_sha}, and push it\n"
        f"  2. Dispatch {workflow} explicitly on that ref\n"
        f"  3. Confirm the resulting run's head commit is {head_sha}; a "
        "ref that moved first runs a different commit, which this gate "
        "will not accept\n"
        "  4. Re-run the deployment, which reads that run by exact "
        "commit\n"
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
    "failed_ci_message",
    "merge_queue_same_tree_note",
    "missing_ci_run_message",
    "no_verdict_ci_message",
    "recover_missing_ci_gate",
    "timed_out_ci_message",
    "unverifiable_ci_target_message",
]
