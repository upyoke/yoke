"""Regressions for the all-failed-jobs report rendering.

Bounding is per job, so these cover that four shards' distinct failure
signatures all survive one report, that every job carries its identity
and link, and that an unavailable or empty log is labelled rather than
silently absent.
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_core.domain.github_actions_failed_job_report import build_failed_job_report
from yoke_core.domain.github_actions_failed_jobs import (
    LOG_AVAILABLE,
    LOG_EXPIRED_OR_MISSING,
    FailedJob,
)


SHARD_NAMES = (
    "test-shard (3.10, 6)",
    "test-shard (3.10, 7)",
    "test-shard (3.13, 6)",
    "test-shard (3.13, 7)",
)


def _failed(name: str, body: str, **overrides: Any) -> FailedJob:
    fields: Dict[str, Any] = {
        "job_id": "900",
        "name": name,
        "conclusion": "failure",
        "html_url": f"https://github.com/o/r/actions/runs/123/job/900",
        "log_text": body,
        "log_status": LOG_AVAILABLE,
        "log_detail": "",
    }
    fields.update(overrides)
    return FailedJob(**fields)


class TestBuildFailedJobReport:
    def test_distinct_failures_survive_the_bound_on_every_shard(self):
        jobs = [
            _failed(name, "\n".join(f"{name} line {i}" for i in range(200)))
            for name in SHARD_NAMES
        ]

        report = build_failed_job_report(
            jobs, repo="o/r", run_id="123", tail_lines=50
        )

        assert report.failed_job_count == 4
        assert report.logs_available_count == 4
        assert report.truncated is True
        for name in SHARD_NAMES:
            assert f"{name} line 199" in report.output
            assert f"{name} line 149" not in report.output
        assert all(entry["truncated"] for entry in report.jobs)
        assert {entry["shown_line_count"] for entry in report.jobs} == {50}
        assert {entry["log_line_count"] for entry in report.jobs} == {200}

    def test_every_job_carries_its_identity_and_link(self):
        report = build_failed_job_report(
            [_failed("build", "boom")], repo="o/r", run_id="123", tail_lines=50
        )

        assert "build" in report.output
        assert "job 900" in report.output
        assert "https://github.com/o/r/actions/runs/123/job/900" in report.output
        assert report.jobs[0]["job_id"] == "900"

    def test_single_failed_job_reports_untruncated(self):
        report = build_failed_job_report(
            [_failed("build", "line a\nline b")],
            repo="o/r",
            run_id="123",
            tail_lines=50,
        )

        assert report.truncated is False
        assert "showing last" not in report.output
        assert "line a" in report.output

    def test_no_failed_jobs_reports_the_run_rather_than_an_error(self):
        report = build_failed_job_report([], repo="o/r", run_id="123", tail_lines=50)

        assert report.failed_job_count == 0
        assert report.jobs == []
        assert "No failed jobs in run 123" in report.output
        assert "https://github.com/o/r/actions/runs/123" in report.output

    def test_unavailable_job_log_is_named_in_the_report(self):
        jobs = [
            _failed("build", "boom"),
            _failed(
                "test",
                "",
                log_status=LOG_EXPIRED_OR_MISSING,
                log_detail="GitHub holds no log for this job",
            ),
        ]

        report = build_failed_job_report(
            jobs, repo="o/r", run_id="123", tail_lines=50
        )

        assert report.failed_job_count == 2
        assert report.logs_available_count == 1
        assert "log unavailable (expired_or_missing)" in report.output
        assert "2 failed job(s), 1 with log output, 1 without" in report.output

    def test_empty_log_is_labelled_rather_than_silent(self):
        report = build_failed_job_report(
            [_failed("build", "\n\n")], repo="o/r", run_id="123", tail_lines=50
        )

        assert "(this job's log is empty)" in report.output
