"""Regressions for locating the failure region of one failed job's log."""

from __future__ import annotations

from runtime.api.domain.github_actions_job_log_samples import (
    FIRST_ASSERTION,
    SUMMARY_LINE,
    TYPE_ERROR,
    build_job_log,
    pytest_job_log,
)
from yoke_core.domain.github_actions_failure_region import (
    REGION_ERROR_STEP,
    REGION_LOG,
    REGION_PYTEST,
    failure_region,
)

UNBOUNDED = 10**9


class TestLocate:
    def test_pytest_region_runs_from_failures_through_the_error(self):
        region = failure_region(pytest_job_log(), max_lines=500, max_bytes=UNBOUNDED)

        assert region.kind == REGION_PYTEST
        assert region.lines[0].startswith("=") and "FAILURES" in region.lines[0]
        assert FIRST_ASSERTION in region.lines
        assert SUMMARY_LINE in region.lines
        assert region.lines[-1] == "##[error]Process completed with exit code 1."
        assert region.trimmed_line_count == 0

    def test_teardown_and_upload_steps_never_appear(self):
        region = failure_region(pytest_job_log(), max_lines=500, max_bytes=UNBOUNDED)

        shown = "\n".join(region.lines)
        assert "Uploaded bytes" not in shown
        assert "Post job cleanup" not in shown
        assert "test_mod_" not in shown

    def test_timestamps_and_color_codes_are_stripped(self):
        region = failure_region(pytest_job_log(), max_lines=500, max_bytes=UNBOUNDED)

        assert not any(line.startswith("2026-") for line in region.lines)
        assert not any("\x1b" in line for line in region.lines)

    def test_non_pytest_failure_shows_the_failing_step_end(self):
        region = failure_region(build_job_log(), max_lines=20, max_bytes=UNBOUNDED)

        assert region.kind == REGION_ERROR_STEP
        assert region.lines[-2:] == [
            TYPE_ERROR,
            "##[error]Process completed with exit code 2.",
        ]
        assert not any("added package" in line for line in region.lines)

    def test_log_without_markers_falls_back_to_its_end_before_teardown(self):
        text = "\n".join([*(f"line {i}" for i in range(30)), "Post job cleanup.", "x"])

        region = failure_region(text, max_lines=5, max_bytes=UNBOUNDED)

        assert region.kind == REGION_LOG
        assert region.lines[-1] == "line 29"
        assert region.trimmed_line_count == 25


class TestBound:
    def test_long_pytest_region_keeps_first_failure_and_summary(self):
        log = pytest_job_log(failures=40, traceback_lines=30)

        region = failure_region(log, max_lines=100, max_bytes=UNBOUNDED)

        assert FIRST_ASSERTION in region.lines
        assert SUMMARY_LINE in region.lines
        assert region.trimmed_line_count > 0
        assert len(region.lines) == 101
        [marker] = [line for line in region.lines if "trimmed" in line]
        assert f"{region.trimmed_line_count} line(s)" in marker
        assert "--full" in marker

    def test_byte_share_bounds_the_region(self):
        log = pytest_job_log(failures=40, traceback_lines=30)

        region = failure_region(log, max_lines=10_000, max_bytes=4_096)

        shown = sum(len(line.encode()) + 1 for line in region.lines)
        assert shown <= 4_096 + 200  # the named trim marker rides on top
        assert region.trimmed_line_count > 0
        assert region.lines[-1].startswith("##[error]")

    def test_one_enormous_line_is_cut_by_name(self):
        text = "##[group]Run x\n" + "y" * 50_000 + "\n##[error]boom"

        region = failure_region(text, max_lines=50, max_bytes=UNBOUNDED)

        assert any("characters cut" in line for line in region.lines)
        assert max(len(line) for line in region.lines) < 3_000
