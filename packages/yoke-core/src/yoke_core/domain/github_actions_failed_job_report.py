"""Rendering for a run's failed jobs — one labelled block per job.

Each job shows its failure region (see
:mod:`github_actions_failure_region`), not its tail, so the assertion
that failed it is on screen rather than its teardown. Bounding is per
job: every job gets an equal share of one report byte budget as well as
the per-job line bound, so a four-shard failure reports four regions and
the whole report fits the function relay's response limit however many
jobs failed. A job whose log is unavailable still gets its block,
carrying the named reason and its GitHub URL, so nothing is concealed by
the bound.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from yoke_core.domain.github_actions_failed_jobs import (
    LOG_AVAILABLE,
    FailedJob,
    LogDownload,
    RunFailures,
)
from yoke_core.domain.github_actions_failure_region import (
    REGION_ERROR_STEP,
    REGION_LOG,
    REGION_PYTEST,
    FailureRegion,
    failure_region,
)


# Log text the whole report may carry across every failed job. JSON
# escaping can grow log text several-fold (control characters become
# six-byte escapes), so this sits far under the relay's 4 MiB response
# limit.
REPORT_LOG_BYTE_BUDGET = 512 * 1024


@dataclass(frozen=True)
class FailedJobReport:
    """The rendered all-failed-jobs report plus its per-job structure."""

    output: str
    truncated: bool
    failed_job_count: int
    logs_available_count: int
    unfinished_job_count: int
    jobs: List[Dict[str, Any]]


def build_failed_job_report(
    failures: RunFailures,
    *,
    repo: str,
    run_id: int | str,
    max_lines: int,
    downloads: Optional[Mapping[str, LogDownload]] = None,
) -> FailedJobReport:
    """Render every failed job as its own labelled, individually bounded block."""
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    unfinished = failures.unfinished_job_count
    still_running = (
        f"{unfinished} job(s) of this run are still running; this read covers "
        "the jobs that have finished — read again once they finish to see "
        "any later failure."
        if unfinished
        else ""
    )
    if not failures.failed:
        lead = (
            f"No failed jobs yet in run {run_id} — {run_url}"
            if unfinished
            else (
                f"No failed jobs in run {run_id}. Its conclusion may be "
                f"cancelled or a startup failure — open {run_url}."
            )
        )
        return FailedJobReport(
            output="\n".join(line for line in (lead, still_running) if line),
            truncated=False,
            failed_job_count=0,
            logs_available_count=0,
            unfinished_job_count=unfinished,
            jobs=[],
        )

    ordered = sorted(failures.failed, key=lambda job: job.name)
    byte_share = REPORT_LOG_BYTE_BUDGET // len(ordered)
    sections: List[str] = []
    summaries: List[Dict[str, Any]] = []
    truncated_any = False
    available = 0
    for position, job in enumerate(ordered, start=1):
        region = failure_region(job.log_text, max_lines=max_lines, max_bytes=byte_share)
        truncated_any = truncated_any or region.trimmed_line_count > 0
        if job.log_status == LOG_AVAILABLE:
            available += 1
        download = (downloads or {}).get(job.job_id)
        sections.append(_section(job, position, len(ordered), region))
        summaries.append(
            {
                "job_id": job.job_id,
                "name": job.name,
                "conclusion": job.conclusion,
                "html_url": job.html_url,
                "log_status": job.log_status,
                "log_detail": job.log_detail,
                "log_line_count": region.log_line_count,
                "region": region.kind,
                "region_line_count": region.region_line_count,
                "trimmed_line_count": region.trimmed_line_count,
                "log_download_url": download.url if download else "",
                "log_download_detail": download.detail if download else "",
            }
        )

    header_lines = [
        f"run {run_id}: {len(ordered)} failed job(s), {available} with log "
        f"output, {len(ordered) - available} without — {run_url}",
    ]
    if still_running:
        header_lines.append(still_running)
    if truncated_any:
        header_lines.append(
            f"Each job shows its failure region, bounded to {max_lines} line(s) "
            "and an equal share of the report size; --full writes every "
            "failed job's complete log to a local file."
        )
    return FailedJobReport(
        output="\n\n".join(["\n".join(header_lines), *sections]),
        truncated=truncated_any,
        failed_job_count=len(ordered),
        logs_available_count=available,
        unfinished_job_count=unfinished,
        jobs=summaries,
    )


_REGION_LABELS = {
    REGION_PYTEST: "pytest failures section",
    REGION_ERROR_STEP: "failing step",
    REGION_LOG: "end of log",
}


def _section(
    job: FailedJob,
    position: int,
    total_jobs: int,
    region: FailureRegion,
) -> str:
    label = (
        f"=== failed job {position}/{total_jobs} · {job.name} · "
        f"job {job.job_id or 'unidentified'} · {job.conclusion or 'failed'} ==="
    )
    lines = [label]
    if job.html_url:
        lines.append(job.html_url)
    if job.log_status != LOG_AVAILABLE:
        lines.append(f"log unavailable ({job.log_status}): {job.log_detail}")
        return "\n".join(lines)
    if not region.lines:
        lines.append("(this job's log is empty)")
        return "\n".join(lines)
    lines.append(
        f"--- {_REGION_LABELS[region.kind]}: {region.region_line_count} of "
        f"{region.log_line_count} log line(s)"
    )
    lines.extend(region.lines)
    return "\n".join(lines)


__all__ = [
    "FailedJobReport",
    "REPORT_LOG_BYTE_BUDGET",
    "build_failed_job_report",
]
