"""Current landing-PR identity and job evidence for safe Actions recovery."""

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain.github_actions_rest import rest_get
from yoke_core.domain.github_actions_failed_jobs import list_run_jobs
from yoke_core.domain.ci_job_outcome import job_started, job_never_started

MAX_NO_VERDICT_ATTEMPTS = 3


def _refused(code: str, message: str, **facts) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        result_payload=facts,
        error=FunctionError(code=code, message=message),
    )


def checked_run(
    root: str,
    pr_number: str,
    run_id: str,
    token: str,
    *,
    expected_head: str = "",
    allow_failure: bool = True,
    get=rest_get,
):
    pr = get(f"{root}/pulls/{pr_number}", token=token)
    run = get(f"{root}/actions/runs/{run_id}", token=token)
    if not isinstance(pr, dict) or not isinstance(run, dict):
        return _refused(
            "ci_rerun_identity_unavailable",
            "GitHub omitted PR or run identity; restore repository read access and retry.",
        )
    head = pr.get("head") or {}
    if not isinstance(head, dict):
        return _refused(
            "ci_rerun_identity_unavailable",
            "PR head identity is malformed; restore GitHub PR reads and retry.",
        )
    sha, branch = head.get("sha"), head.get("ref")
    if pr.get("state") != "open" or not sha or not branch:
        return _refused(
            "ci_rerun_pr_not_open",
            "Landing PR is not open with a readable head; inspect the item's landing PR before retrying.",
        )
    if run.get("head_sha") != sha or (expected_head and sha != expected_head):
        return _refused(
            "ci_rerun_stale_head",
            f"Run {run_id} head {run.get('head_sha')} differs from PR head {sha}; use the newest run for the current PR head.",
        )
    head_repo = head.get("repo") or {}
    if (
        not isinstance(head_repo, dict)
        or head_repo.get("full_name") != root.removeprefix("/repos/")
        or run.get("head_branch") != branch
    ):
        return _refused(
            "ci_rerun_ref_mismatch",
            "Run and landing PR must name the bound repository's same branch; use this item's own landing-PR run.",
        )
    workflow_id = run.get("workflow_id")
    if (
        not isinstance(workflow_id, int)
        or isinstance(workflow_id, bool)
        or workflow_id < 1
    ):
        return _refused(
            "ci_rerun_identity_unavailable",
            "Run has no valid workflow id; restore GitHub run reads before retrying.",
        )
    latest = get(
        f"{root}/actions/workflows/{workflow_id}/runs",
        query={"branch": branch, "per_page": "1"},
        token=token,
    )
    runs = latest.get("workflow_runs") if isinstance(latest, dict) else None
    if (
        not isinstance(runs, list)
        or not runs
        or not isinstance(runs[0], dict)
        or not runs[0].get("id")
    ):
        return _refused(
            "ci_rerun_identity_unavailable",
            "Newest workflow-run identity is unavailable; restore GitHub workflow reads and retry.",
        )
    if str(runs[0]["id"]) != run_id:
        return _refused(
            "ci_rerun_superseded",
            f"Run {run_id} is older than newest run {runs[0]['id']} for workflow {workflow_id} on {branch}; inspect the newer run instead. No rerun was sent.",
        )
    if (
        str(run.get("id")) != run_id
        or run.get("status") != "completed"
        or run.get("conclusion")
        not in (
            {"failure", "timed_out", "cancelled", "startup_failure", "stale"}
            if allow_failure
            else {"cancelled", "startup_failure", "stale", "failure"}
        )
    ):
        return _refused(
            "ci_rerun_not_failed",
            "Only a completed failed, timed-out, cancelled or never-started run can be recovered; wait for active CI or inspect the current run.",
        )
    jobs = list_run_jobs(root.removeprefix("/repos/"), run_id, token=token)
    real_failure = any(
        job_started(job) and job.get("conclusion") in {"failure", "timed_out"}
        for job in jobs
    )
    no_verdict = not real_failure and (
        run.get("conclusion") in {"cancelled", "startup_failure", "stale"}
        or not jobs
        or any(job_never_started(job) for job in jobs)
    )
    if not allow_failure and not no_verdict:
        return _refused(
            "ci_rerun_verdict",
            "Started jobs failed; fix the cause on the lane, commit and rerun verification. No rerun was sent.",
        )
    attempt = run.get("run_attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        return _refused(
            "ci_rerun_identity_unavailable",
            "Run attempt is unavailable; restore GitHub run reads before retrying.",
        )
    if no_verdict and attempt >= MAX_NO_VERDICT_ATTEMPTS:
        return _refused(
            "ci_rerun_limit",
            f"Run {run_id} reached {attempt} attempts without a verdict; inspect its job annotations and repair runner capacity, labels or workflow limits before starting a fresh declared workflow attempt. Verify its exact head and required-check replacement before retrying merge.",
        )
    endpoint = (
        "rerun" if not any(job_started(job) for job in jobs) else "rerun-failed-jobs"
    )
    return {**run, "rerun_endpoint": endpoint}
