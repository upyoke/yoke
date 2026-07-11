"""GitHub workflow dispatch arguments and existing-run reconciliation."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)


def _dispatch_correlation_input(config: Dict[str, Any]) -> str:
    """Return the recognized standard correlation input, otherwise empty."""
    value = str(config.get("dispatch_correlation_input") or "").strip()
    return value if value == WORKFLOW_DISPATCH_CORRELATION_INPUT else ""


class _WorkflowReconciliationError(RuntimeError):
    """The existing-run probe could not establish GitHub workflow truth."""


def _trigger_args(
    github_repo: str,
    workflow: str,
    workflow_ref: str,
    workflow_inputs: Dict[str, str],
    *,
    request_id: str = "",
    correlation_input: str = "",
) -> list[str]:
    operation = "trigger" if correlation_input else "trigger-once"
    args = [operation, github_repo, workflow, "--ref", workflow_ref]
    for key in sorted(workflow_inputs):
        args.extend(["--input", f"{key}={workflow_inputs[key]}"])
    if request_id:
        args.extend(["--request-id", request_id])
    if correlation_input:
        args.extend(["--correlation-input", correlation_input])
    return args


def _reconciliation_failure(
    operation: str,
    result: Any,
) -> _WorkflowReconciliationError:
    detail = (result.stderr or result.stdout or "").strip()
    suffix = f": {detail}" if detail else ""
    return _WorkflowReconciliationError(
        f"GitHub Actions {operation} failed with exit code "
        f"{result.returncode}{suffix}"
    )


def _found_run_id(
    result: Any,
    *,
    workflow: str,
    head_sha: str,
) -> str:
    """Decode find-run without conflating relay failure with not-found."""
    value = result.stdout.strip()
    if result.returncode == 1 and value == "not_found":
        return ""
    if result.returncode != 0:
        raise _reconciliation_failure(
            f"find-run for {workflow} @ {head_sha[:8]}", result,
        )
    if not value or value == "not_found":
        raise _WorkflowReconciliationError(
            "GitHub Actions find-run returned an invalid successful response "
            f"for {workflow} @ {head_sha[:8]}: {value or '<empty>'}"
        )
    return value


def _find_existing_workflow_run(
    github_repo: str,
    workflow: str,
    head_sha: str,
    *,
    project: str,
    sd: Optional[str],
    github_actions: Callable[..., Any],
) -> tuple[str, bool, str]:
    """Return a reusable run or a deterministic fresh-dispatch scope."""
    result = github_actions(
        "find-run", github_repo, workflow, head_sha, project=project, sd=sd,
    )
    ga_run_id = _found_run_id(result, workflow=workflow, head_sha=head_sha)
    if not ga_run_id:
        return "", False, ""

    print(f"  Found existing run {ga_run_id} for {workflow} @ {head_sha[:8]}")
    jobs_result = github_actions(
        "jobs-count", github_repo, ga_run_id, project=project, sd=sd,
    )
    if jobs_result.returncode != 0:
        raise _reconciliation_failure(
            f"jobs-count for workflow run {ga_run_id}", jobs_result,
        )
    raw_job_count = jobs_result.stdout.strip()
    try:
        job_count = int(raw_job_count)
    except (TypeError, ValueError) as exc:
        raise _WorkflowReconciliationError(
            "GitHub Actions jobs-count returned a non-integer successful "
            f"response for workflow run {ga_run_id}: "
            f"{raw_job_count or '<empty>'}"
        ) from exc
    if job_count < 0:
        raise _WorkflowReconciliationError(
            "GitHub Actions jobs-count returned a negative count for "
            f"workflow run {ga_run_id}: {job_count}"
        )
    if job_count == 0:
        print(f"  Existing run {ga_run_id} has zero jobs — triggering fresh run")
        return "", False, f"empty:{ga_run_id}"

    poll_result = github_actions(
        "poll", github_repo, ga_run_id, project=project, sd=sd,
    )
    status = poll_result.stdout.strip()
    if poll_result.returncode == 0 and status == "success":
        print("  Run already completed successfully — skipping deploy trigger")
        return ga_run_id, True, ""
    if poll_result.returncode == 1 and status.startswith("failed:"):
        print(
            f"  Existing run {ga_run_id} failed — treating as stale, "
            "auto-triggering fresh run"
        )
        return "", False, f"failed:{ga_run_id}"
    if poll_result.returncode not in (2, 3):
        if poll_result.returncode != 0:
            raise _reconciliation_failure(
                f"poll for workflow run {ga_run_id}", poll_result,
            )
        raise _WorkflowReconciliationError(
            "GitHub Actions poll returned an invalid successful response for "
            f"workflow run {ga_run_id}: {status or '<empty>'}"
        )
    if not status:
        raise _WorkflowReconciliationError(
            "GitHub Actions poll returned an empty in-progress response for "
            f"workflow run {ga_run_id}"
        )

    print(f"  Existing run status: {status} — attaching to it")
    return ga_run_id, False, ""


__all__ = [
    "_WorkflowReconciliationError",
    "_dispatch_correlation_input",
    "_find_existing_workflow_run",
    "_found_run_id",
    "_trigger_args",
]
