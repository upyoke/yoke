"""Regressions for the all-failed-jobs report rendering.

Bounding is per job, so these cover that four shards' distinct failure
regions all survive one report, that many failed jobs together stay
inside the report byte budget, that every job carries its identity and
link, that unfinished sibling jobs are named, and that an unavailable or
empty log is labelled rather than silently absent.
"""

from __future__ import annotations

from typing import Any, Dict


from runtime.api.domain.github_actions_job_log_samples import (
    FIRST_ASSERTION,
    SUMMARY_LINE,
    pytest_job_log,
)
from yoke_core.domain.github_actions_failed_job_report import (
    REPORT_LOG_BYTE_BUDGET,
    build_failed_job_report,
)
from yoke_core.domain.github_actions_failed_jobs import (
    LOG_AVAILABLE,
    LOG_EXPIRED_OR_MISSING,
    FailedJob,
    LogDownload,
    RunFailures,
)


SHARD_NAMES = (
    "test-shard (3.10, 6)",
    "test-shard (3.10, 7)",
    "test-shard (3.13, 6)",
    "test-shard (3.13, 7)",
)


def _report(jobs, *, unfinished: int = 0, max_lines: int = 200, **kwargs: Any):
    return build_failed_job_report(
        RunFailures(failed=list(jobs), unfinished_job_count=unfinished),
        repo="o/r",
        run_id="123",
        max_lines=max_lines,
        **kwargs,
    )


def _failed(name: str, body: str, **overrides: Any) -> FailedJob:
    fields: Dict[str, Any] = {
        "job_id": "900",
        "name": name,
        "conclusion": "failure",
        "html_url": "https://github.com/o/r/actions/runs/123/job/900",
        "log_text": body,
        "log_status": LOG_AVAILABLE,
        "log_detail": "",
    }
    fields.update(overrides)
    return FailedJob(**fields)


class TestBuildFailedJobReport:
    def test_shows_the_failure_region_not_the_teardown_tail(self):
        report = _report([_failed("tests", pytest_job_log())])

        assert FIRST_ASSERTION in report.output
        assert SUMMARY_LINE in report.output
        assert "Uploaded bytes" not in report.output
        assert "Post job cleanup" not in report.output
        assert report.jobs[0]["region"] == "pytest_failures"
        assert "--- pytest failures section:" in report.output

    def test_distinct_failures_survive_the_bound_on_every_shard(self):
        jobs = [
            _failed(name, pytest_job_log(failures=30, traceback_lines=20))
            for name in SHARD_NAMES
        ]

        report = _report(jobs, max_lines=50)

        assert report.failed_job_count == 4
        assert report.logs_available_count == 4
        assert report.truncated is True
        assert report.output.count(FIRST_ASSERTION) == 4
        assert report.output.count("30 failed, 4123 passed") == 4
        assert all(entry["trimmed_line_count"] > 0 for entry in report.jobs)
        assert "bounded to 50 line(s)" in report.output

    def test_many_failed_jobs_stay_inside_the_report_budget(self):
        jobs = [
            _failed(
                f"shard {index}",
                pytest_job_log(failures=200, traceback_lines=40),
                job_id=str(900 + index),
            )
            for index in range(64)
        ]

        report = _report(jobs, max_lines=100_000)

        assert len(report.output.encode("utf-8")) < REPORT_LOG_BYTE_BUDGET + 64 * 1024
        assert report.output.count(FIRST_ASSERTION) == 64
        assert report.output.count("200 failed, 4123 passed") == 64
        assert all(entry["trimmed_line_count"] > 0 for entry in report.jobs)

    def test_unfinished_siblings_are_named_beside_finished_failures(self):
        report = _report([_failed("shard 1", pytest_job_log())], unfinished=3)

        assert report.unfinished_job_count == 3
        assert "3 job(s) of this run are still running" in report.output
        assert FIRST_ASSERTION in report.output

    def test_no_failures_yet_while_jobs_run_is_not_called_a_conclusion(self):
        report = _report([], unfinished=2)

        assert "No failed jobs yet in run 123" in report.output
        assert "2 job(s) of this run are still running" in report.output
        assert "cancelled" not in report.output

    def test_every_job_carries_its_identity_and_link(self):
        report = _report([_failed("build", "boom")])

        assert "build" in report.output
        assert "job 900" in report.output
        assert "https://github.com/o/r/actions/runs/123/job/900" in report.output
        assert report.jobs[0]["job_id"] == "900"

    def test_download_addresses_ride_in_the_job_structure_only(self):
        signed = "https://results.example/900.txt?sig=x"
        report = _report(
            [_failed("build", "boom")],
            downloads={"900": LogDownload(url=signed, detail="")},
        )

        assert report.jobs[0]["log_download_url"] == signed
        assert signed not in report.output

    def test_single_short_failed_job_reports_untruncated(self):
        report = _report([_failed("build", "line a\nline b")])

        assert report.truncated is False
        assert "trimmed" not in report.output
        assert "line a" in report.output

    def test_no_failed_jobs_reports_the_run_rather_than_an_error(self):
        report = _report([])

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

        report = _report(jobs)

        assert report.failed_job_count == 2
        assert report.logs_available_count == 1
        assert "log unavailable (expired_or_missing)" in report.output
        assert "2 failed job(s), 1 with log output, 1 without" in report.output

    def test_empty_log_is_labelled_rather_than_silent(self):
        report = _report([_failed("build", "\n\n")])

        assert "(this job's log is empty)" in report.output
