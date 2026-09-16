"""Failed-job inventory for one GitHub Actions run.

A sharded workflow fails in several jobs at once, and triage needs every
one of those signatures. This module lists a run's jobs (following the
provider's pagination) and collects the log text of every failed one,
recording a named reason for each job whose log GitHub could not hand
over instead of dropping it.

Log text comes from the whole-run archive when it is available, and from
the per-job endpoint for any failed job the archive did not carry, so a
job is never missing because its archive entry was not found.
Rendering lives in :mod:`github_actions_failed_job_report`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestNotFoundError,
    RestTransportError,
)
from yoke_core.domain.github_actions_log_archive import parse_failed_log_zip
from yoke_core.domain.github_actions_logs import fetch_failed_log_zip, fetch_job_log
from yoke_core.domain.github_actions_rest import rest_get
from yoke_core.domain.github_response_safety import redact_exact_secrets


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
        if isinstance(reported, int) and not isinstance(reported, bool) and reported >= 0:
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
) -> List[FailedJob]:
    """Return one :class:`FailedJob` per failed job of *run_id*."""
    failed = [
        job
        for job in list_run_jobs(repo, run_id, token=token)
        if str(job.get("conclusion") or "") in FAILED_JOB_CONCLUSIONS
    ]
    if not failed:
        return []
    archive = _archive_logs(repo, run_id, token=token)
    return [_failed_job(repo, job, archive, token=token) for job in failed]


def _archive_logs(repo: str, run_id: int | str, *, token: str) -> Dict[str, str]:
    """Whole-run log archive as ``{job_name: text}``, empty when unusable.

    The archive is a bulk shortcut, never the only source, so NO failure
    reaching it is fatal: refused, unreachable, absent, and over-limit
    archives all yield an empty mapping. Every job missing from it is
    then fetched individually by job id, which either returns that job's
    log or gives it a named per-job reason — both of which beat losing
    the whole inventory to one archive-wide refusal.
    """
    try:
        zip_bytes = fetch_failed_log_zip(repo, run_id, token=token)
        parsed = parse_failed_log_zip(zip_bytes)
    except RestTransportError:
        return {}
    return {
        name: redact_exact_secrets(body, (token,)) for name, body in parsed.items()
    }


def _failed_job(
    repo: str,
    job: Dict[str, str],
    archive: Dict[str, str],
    *,
    token: str,
) -> FailedJob:
    job_id = str(job.get("id") or "")
    name = str(job.get("name") or "").strip() or f"job {job_id or 'unnamed'}"
    fields = {
        "job_id": job_id,
        "name": name,
        "conclusion": str(job.get("conclusion") or ""),
        "html_url": str(job.get("html_url") or ""),
    }
    archived = archive.get(name)
    if archived is not None:
        return FailedJob(
            **fields, log_text=archived, log_status=LOG_AVAILABLE, log_detail=""
        )
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
    except RestNotFoundError:
        status, detail = (
            LOG_EXPIRED_OR_MISSING,
            "GitHub holds no log for this job — run logs expire with the "
            "repository's retention window; open the job URL above",
        )
    except RestAuthError as exc:
        status, detail = (
            LOG_PERMISSION_DENIED,
            f"GitHub refused this job's log ({exc}); give the project's "
            "GitHub credential Actions read access on this repository",
        )
    except RestTransportError as exc:
        status, detail = (
            LOG_FETCH_FAILED,
            f"this job's log could not be fetched ({exc}); re-run the read, "
            "then open the job URL above",
        )
    else:
        return FailedJob(
            **fields, log_text=text, log_status=LOG_AVAILABLE, log_detail=""
        )
    return FailedJob(**fields, log_text="", log_status=status, log_detail=detail)
