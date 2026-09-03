"""Per-check progress lines and result-payload report rendering.

The wrapper that follows a doctor run recognises exactly two line
shapes, and every runner has to produce them: the source-dev engine
entrypoint, the ``doctor.run.run`` handler, and the client-side
composition passes of a relayed run. These tests pin the shapes, the
opt-in sink, and the shared executor that emits for all three.
"""

from __future__ import annotations

import io

from yoke_contracts.field_note_text import FOOTER as FIELD_NOTE_FOOTER
from yoke_core.engines import doctor_progress
from yoke_core.engines.doctor_check_execution import execute_check_isolated
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_result_report import (
    remediation_with_footer,
    report_from_result,
)
from yoke_core.tools.watch_doctor import classify_doctor_line
from yoke_core.tools._watch_throttle import LineClass


class _Conn:
    def rollback(self) -> None:
        pass


def _passing(conn, args, rec) -> None:
    rec.record("HC-example", "Example", "PASS", "")


def _failing(conn, args, rec) -> None:
    rec.record("HC-example", "Example", "FAIL", "broken")


def _raising(conn, args, rec) -> None:
    raise RuntimeError("boom")


def _run_one(fn) -> str:
    stream = io.StringIO()
    rec = RecordCollector()
    check = HealthCheck(slug="example", name="Example", fn=fn)
    with doctor_progress.progress_to(stream):
        execute_check_isolated(_Conn(), DoctorArgs(quick=True), rec, check)
    return stream.getvalue()


class TestSinkIsOptIn:
    def test_no_sink_emits_nothing(self) -> None:
        rec = RecordCollector()
        check = HealthCheck(slug="example", name="Example", fn=_passing)
        # Server-side dispatch runs this loop with no sink installed.
        execute_check_isolated(_Conn(), DoctorArgs(quick=True), rec, check)
        assert [r.result for r in rec.results] == ["PASS"]

    def test_sink_is_removed_on_exit(self) -> None:
        stream = io.StringIO()
        with doctor_progress.progress_to(stream):
            doctor_progress.emit("inside")
        doctor_progress.emit("outside")
        assert stream.getvalue() == "inside\n"


class TestExecutorEmitsBothShapes:
    def test_started_and_result_lines(self) -> None:
        assert _run_one(_passing) == "running HC-example\nHC-example: PASS\n"

    def test_failure_verdict_is_emitted(self) -> None:
        assert "HC-example: FAIL" in _run_one(_failing)

    def test_internal_error_still_reports_a_verdict(self) -> None:
        # A check that raises must not leave the run silent about it.
        emitted = _run_one(_raising)
        assert "running HC-example" in emitted
        assert "HC-internal-error: FAIL" in emitted

    def test_emitted_lines_classify_for_the_watcher(self) -> None:
        lines = _run_one(_failing).splitlines()
        assert classify_doctor_line(lines[0]).cls is LineClass.PROGRESS
        assert classify_doctor_line(lines[1]).cls is LineClass.URGENT


class TestWithheldVerdicts:
    """A runner that will rewrite a verdict emits the rewritten one."""

    def test_verdict_is_withheld_but_start_line_still_streams(self) -> None:
        stream = io.StringIO()
        rec = RecordCollector()
        check = HealthCheck(slug="example", name="Example", fn=_failing)
        with doctor_progress.progress_to(stream):
            with doctor_progress.verdicts_withheld():
                execute_check_isolated(
                    _Conn(), DoctorArgs(quick=True), rec, check
                )
        # Liveness survives; the raw verdict does not reach the stream.
        assert stream.getvalue() == "running HC-example\n"

    def test_caller_emits_the_rewritten_verdict(self) -> None:
        stream = io.StringIO()
        rec = RecordCollector()
        check = HealthCheck(slug="example", name="Example", fn=_failing)
        with doctor_progress.progress_to(stream):
            with doctor_progress.verdicts_withheld():
                execute_check_isolated(
                    _Conn(), DoctorArgs(quick=True), rec, check
                )
                rec.results[0].result = "N/A"
            for record in rec.results:
                doctor_progress.check_finished(record.check_id, record.result)
        assert "HC-example: FAIL" not in stream.getvalue()
        assert "HC-example: N/A" in stream.getvalue()

    def test_a_rewritten_verdict_does_not_wake_urgently(self) -> None:
        # N/A is NOISE to the watcher, so a reclassified check lands in the
        # raw capture without waking a follower for a finding that is not one.
        assert classify_doctor_line("HC-example: N/A").cls is LineClass.NOISE
        assert classify_doctor_line("HC-example: FAIL").cls is LineClass.URGENT

    def test_withholding_ends_with_the_block(self) -> None:
        stream = io.StringIO()
        with doctor_progress.progress_to(stream):
            with doctor_progress.verdicts_withheld():
                doctor_progress.check_finished("HC-inside", "FAIL")
            doctor_progress.check_finished("HC-outside", "FAIL")
        assert stream.getvalue() == "HC-outside: FAIL\n"


class TestRelayedRows:
    def test_rows_render_result_lines(self) -> None:
        stream = io.StringIO()
        with doctor_progress.progress_to(stream):
            doctor_progress.emit_result_rows(
                [
                    {"hc": "HC-one", "severity": "PASS"},
                    {"hc": "HC-two", "severity": "WARN"},
                ]
            )
        assert stream.getvalue() == "HC-one: PASS\nHC-two: WARN\n"

    def test_not_applicable_rows_are_skipped(self) -> None:
        # The in-process loops announce only checks they execute; a run's
        # N/A set is reported in the report's own section instead.
        stream = io.StringIO()
        with doctor_progress.progress_to(stream):
            doctor_progress.emit_result_rows(
                [{"hc": "HC-skipped", "severity": "N/A"}]
            )
        assert stream.getvalue() == ""


class TestRemediationFooter:
    def test_appends_when_absent(self) -> None:
        wrapped = remediation_with_footer("fix the column drift")
        assert wrapped.startswith("fix the column drift")
        assert wrapped.endswith(FIELD_NOTE_FOOTER)

    def test_is_idempotent(self) -> None:
        # Re-wrapping must not double-append; the second call sees the
        # footer already present and returns the input unchanged.
        once = remediation_with_footer("first prompt")
        twice = remediation_with_footer(once)
        assert once == twice
        assert twice.count(FIELD_NOTE_FOOTER) == 1


class TestReportFromResult:
    def _result(self) -> dict:
        return {
            "results": [
                {
                    "hc": "HC-one",
                    "name": "First",
                    "severity": "PASS",
                    "detail": "",
                },
                {
                    "hc": "HC-two",
                    "name": "Second",
                    "severity": "FAIL",
                    "detail": "it broke",
                },
            ],
            "fail_count": 1,
        }

    def test_renders_the_ouroboros_report(self) -> None:
        report = report_from_result(self._result())
        assert report.startswith("# Ouroboros Health Report")
        assert "2 checks run: 1 passed, 0 warnings, 1 failure" in report
        assert "### HC-two: Second" in report

    def test_failure_details_carry_the_field_note_footer(self) -> None:
        report = report_from_result(self._result())
        assert remediation_with_footer("it broke") in report

    def test_empty_result_still_renders_a_report(self) -> None:
        assert "0 checks run" in report_from_result({"results": []})
