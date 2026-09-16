"""Rendering for a run's failed jobs — one labelled block per job.

Bounding is per job, so a four-shard failure reports four tails rather
than whichever job's output happened to land last in one shared tail. A
job whose log is unavailable still gets its block, carrying the named
reason and its GitHub URL, so nothing is concealed by the bound.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from yoke_core.domain.github_actions_failed_jobs import LOG_AVAILABLE, FailedJob


@dataclass(frozen=True)
class FailedJobReport:
    """The rendered all-failed-jobs report plus its per-job structure."""

    output: str
    truncated: bool
    failed_job_count: int
    logs_available_count: int
    jobs: List[Dict[str, Any]]


def build_failed_job_report(
    jobs: Sequence[FailedJob],
    *,
    repo: str,
    run_id: int | str,
    tail_lines: int,
) -> FailedJobReport:
    """Render every failed job as its own labelled, individually bounded block."""
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    if not jobs:
        return FailedJobReport(
            output=(
                f"No failed jobs in run {run_id}. Its conclusion may be "
                f"cancelled or a startup failure — open {run_url}."
            ),
            truncated=False,
            failed_job_count=0,
            logs_available_count=0,
            jobs=[],
        )

    ordered = sorted(jobs, key=lambda job: job.name)
    sections: List[str] = []
    summaries: List[Dict[str, Any]] = []
    truncated_any = False
    available = 0
    for position, job in enumerate(ordered, start=1):
        shown, total_lines, truncated = _tail(job.log_text, tail_lines)
        truncated_any = truncated_any or truncated
        if job.log_status == LOG_AVAILABLE:
            available += 1
        sections.append(
            _section(job, position, len(ordered), shown, total_lines, truncated)
        )
        summaries.append(
            {
                "job_id": job.job_id,
                "name": job.name,
                "conclusion": job.conclusion,
                "html_url": job.html_url,
                "log_status": job.log_status,
                "log_detail": job.log_detail,
                "log_line_count": total_lines,
                "shown_line_count": len(shown),
                "truncated": truncated,
            }
        )

    header = (
        f"run {run_id}: {len(ordered)} failed job(s), {available} with log "
        f"output, {len(ordered) - available} without — {run_url}"
    )
    if truncated_any:
        header += (
            f"\nEach job below shows its last {tail_lines} log line(s); "
            "raise --tail-lines to read further back."
        )
    return FailedJobReport(
        output="\n\n".join([header, *sections]),
        truncated=truncated_any,
        failed_job_count=len(ordered),
        logs_available_count=available,
        jobs=summaries,
    )


def _section(
    job: FailedJob,
    position: int,
    total_jobs: int,
    shown: List[str],
    total_lines: int,
    truncated: bool,
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
    if not shown:
        lines.append("(this job's log is empty)")
        return "\n".join(lines)
    if truncated:
        lines.append(f"... showing last {len(shown)} of {total_lines} log lines")
    lines.extend(shown)
    return "\n".join(lines)


def _tail(text: str, tail_lines: int) -> tuple[List[str], int, bool]:
    lines = text.strip("\n").splitlines()
    if not any(line.strip() for line in lines):
        return [], 0, False
    if len(lines) <= tail_lines:
        return lines, len(lines), False
    return lines[-tail_lines:], len(lines), True


__all__ = [
    "FailedJobReport",
    "build_failed_job_report",
]
