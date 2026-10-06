"""Failed-job inventory for one GitHub Actions run.

A sharded workflow fails in several jobs at once, and triage needs every
one of those signatures. This module lists a run's jobs (following the
provider's pagination) and collects the log text of every failed one,
recording a named reason for each job whose log GitHub could not hand
over instead of dropping it.

Every failed job is read by its own job id the moment it has finished,
so a red shard is readable while sibling jobs keep the run in progress.
The inventory also counts the jobs that have not finished, so a report
can say a later failure may still arrive. Rendering lives in
:mod:`github_actions_failed_job_report`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestNotFoundError,
    RestTransportError,
)
from yoke_core.domain.github_actions_logs import (
    JobLogTooLargeError,
    fetch_job_log,
    job_log_download_url,
)
from yoke_core.domain.github_actions_rest import rest_get


# Conclusions that mean "this job is a failure an agent must read". A
# cancelled job carries no failure signature and is deliberately absent.
FAILED_JOB_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})

JOBS_PAGE_SIZE = 100
# Ceiling on paged job reads. A run above it is refused by name rather
# than paged forever.
JOBS_PAGE_LIMIT = 50

LOG_AVAILABLE = "available"
LOG_EXPIRED_OR_MISSING = "expired_or_missing"
LOG_PERMISSION_DENIED = "permission_denied"
LOG_FETCH_FAILED = "fetch_failed"


@dataclass(frozen=True)
class FailedJob:
    """One failed job of a run, with its log text or the reason there is none."""

    job_id: str
    name: str
    conclusion: str
    html_url: str
    log_text: str
    log_status: str
    log_detail: str


@dataclass(frozen=True)
class RunFailures:
    """Every finished failed job of a run, plus the jobs still running."""

    failed: List[FailedJob] = field(default_factory=list)
    unfinished_job_count: int = 0


@dataclass(frozen=True)
class LogDownload:
    """Where one job's complete log can be downloaded, or why it cannot."""

    url: str
    detail: str


def list_run_jobs(repo: str, run_id: int | str, *, token: str) -> List[Dict[str, str]]:
    """List every job of *run_id*, following the provider's pagination.

    One page holds at most :data:`JOBS_PAGE_SIZE` jobs, so a matrix wider
    than that reports only its first page unless every page is read.
    """
    jobs: List[Dict[str, str]] = []
    total: Optional[int] = None
    for page in range(1, JOBS_PAGE_LIMIT + 1):
        listing = rest_get(
            f"/repos/{repo}/actions/runs/{run_id}/jobs",
            query={"per_page": str(JOBS_PAGE_SIZE), "page": str(page)},
            token=token,
        )
        if listing is None:
            raise RestNotFoundError(
                f"no job listing for run {run_id} in {repo}: check the run id "
                "and that the project's GitHub binding names this repository",
                status=404,
            )
        raw = listing.get("jobs") if isinstance(listing, dict) else None
        if not isinstance(raw, list):
            raise RestTransportError(
                f"GitHub returned an unreadable job listing for run {run_id}; "
                "re-run the read, and report it if it repeats",
            )
        page_jobs = [job for job in raw if isinstance(job, dict)]
        jobs.extend(page_jobs)
        reported = listing.get("total_count")
        if (
            isinstance(reported, int)
            and not isinstance(reported, bool)
            and reported >= 0
        ):
            total = reported
        if len(page_jobs) < JOBS_PAGE_SIZE:
            return jobs
        if total is not None and len(jobs) >= total:
            return jobs
    raise RestTransportError(
        f"run {run_id} listed more than {JOBS_PAGE_LIMIT * JOBS_PAGE_SIZE} jobs; "
        "read one job at a time from its GitHub job URL instead",
    )


def collect_failed_jobs(
    repo: str,
    run_id: int | str,
    *,
    token: str,
) -> RunFailures:
    """Read every finished failed job of *run_id* by its own job id."""
    jobs = list_run_jobs(repo, run_id, token=token)
    failed = [
        _failed_job(repo, job, token=token)
        for job in jobs
        if str(job.get("conclusion") or "") in FAILED_JOB_CONCLUSIONS
    ]
    unfinished = sum(1 for job in jobs if str(job.get("status") or "") != "completed")
    return RunFailures(failed=failed, unfinished_job_count=unfinished)


def resolve_log_downloads(
    repo: str,
    jobs: List[FailedJob],
    *,
    token: str,
) -> Dict[str, LogDownload]:
    """Map each failed job id to its complete-log download address."""
    downloads: Dict[str, LogDownload] = {}
    for job in jobs:
        if not job.job_id:
            continue
        try:
            url = job_log_download_url(repo, job.job_id, token=token)
        except RestTransportError as exc:
            _, detail = _unavailable(exc)
            downloads[job.job_id] = LogDownload(url="", detail=detail)
        else:
            downloads[job.job_id] = LogDownload(url=url, detail="")
    return downloads


def _failed_job(repo: str, job: Dict[str, str], *, token: str) -> FailedJob:
    job_id = str(job.get("id") or "")
    name = str(job.get("name") or "").strip() or f"job {job_id or 'unnamed'}"
    fields = {
        "job_id": job_id,
        "name": name,
        "conclusion": str(job.get("conclusion") or ""),
        "html_url": str(job.get("html_url") or ""),
    }
    if not job_id:
        return FailedJob(
            **fields,
            log_text="",
            log_status=LOG_FETCH_FAILED,
            log_detail=(
                "GitHub listed this failed job without an id, so its log has "
                "no address; open the run in GitHub to read it"
            ),
        )
    try:
        text = fetch_job_log(repo, job_id, token=token)
    except RestTransportError as exc:
        status, detail = _unavailable(exc)
        return FailedJob(**fields, log_text="", log_status=status, log_detail=detail)
    return FailedJob(**fields, log_text=text, log_status=LOG_AVAILABLE, log_detail="")


def _unavailable(exc: RestTransportError) -> tuple[str, str]:
    if isinstance(exc, RestNotFoundError):
        return (
            LOG_EXPIRED_OR_MISSING,
            "GitHub holds no log for this job — run logs expire with the "
            "repository's retention window; open the job URL above",
        )
    if isinstance(exc, RestAuthError):
        return (
            LOG_PERMISSION_DENIED,
            f"GitHub refused this job's log ({exc}); give the project's "
            "GitHub credential Actions read access on this repository",
        )
    if isinstance(exc, JobLogTooLargeError):
        return (
            LOG_FETCH_FAILED,
            f"this job's log is too large to read into the report ({exc}); "
            "re-run with --full to write the complete log to a local file",
        )
    return (
        LOG_FETCH_FAILED,
        f"this job's log could not be fetched ({exc}); re-run the read, "
        "then open the job URL above",
    )
