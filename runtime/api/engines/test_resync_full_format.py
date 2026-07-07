"""Tests for resync's doctor-format output.

`_emit_doctor_format` renders pure in-memory drift/orphan inputs into
HC-* lines — no DB access (the retired pending-sync-failures HC was the
only DB read; it scanned an events shape with zero live rows and was
deleted with the telemetry-only events cutover).
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from yoke_core.engines.resync import DriftRecord, _emit_doctor_format


class TestDoctorFormat:
    """Doctor-format HC-* line output."""

    def test_all_pass_when_no_issues(self):
        """All HCs show PASS when no issues found."""
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], [], "detect")
        output = captured.getvalue()
        assert "HC-missing-gh-issues|Missing GitHub issues|PASS|" in output
        assert "HC-title-drift|Title drift|PASS|" in output
        assert "HC-body-drift|Body drift|PASS|" in output
        assert "HC-state-drift|State drift|PASS|" in output
        assert "HC-label-drift|Label drift|PASS|" in output
        assert "HC-frozen-label-drift|Frozen label drift|PASS|" in output
        assert "HC-orphan-epic-tasks|Orphan epic tasks|PASS|" in output
        assert "HC-reverse-completeness|Reverse completeness|PASS|" in output
        assert "HC-comment-sync|Comment sync|PASS|" in output

    def test_warn_on_title_drift(self):
        """Doctor format shows WARN for title drift."""
        drifts = [DriftRecord("YOK-42", "title", "Local Title", "GitHub Title")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], drifts, "detect")
        output = captured.getvalue()
        assert "HC-title-drift|Title drift|WARN|" in output
        assert "YOK-42" in output

    def test_warn_on_body_drift(self):
        drifts = [DriftRecord("YOK-42", "body", "<local body>", "<github body>")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], drifts, "detect")
        output = captured.getvalue()
        assert "HC-body-drift|Body drift|WARN|" in output

    def test_warn_on_state_drift(self):
        drifts = [DriftRecord("YOK-42", "state", "CLOSED", "OPEN")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], drifts, "detect")
        output = captured.getvalue()
        assert "HC-state-drift|State drift|WARN|" in output

    def test_warn_on_label_drift(self):
        drifts = [DriftRecord("YOK-42", "label-status", "status:done", "status:idea")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], drifts, "detect")
        output = captured.getvalue()
        assert "HC-label-drift|Label drift|WARN|" in output

    def test_warn_on_frozen_label_drift(self):
        drifts = [DriftRecord("YOK-42", "label-frozen", "frozen:true", "frozen:absent")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], drifts, "detect")
        output = captured.getvalue()
        assert "HC-frozen-label-drift|Frozen label drift|WARN|" in output

    def test_warn_on_comment_drift(self):
        drifts = [DriftRecord("YOK-42", "comment", "has-status-comment", "missing")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], drifts, "detect")
        output = captured.getvalue()
        assert "HC-comment-sync|Comment sync|WARN|" in output

    def test_warn_on_local_orphans(self):
        orphans = [("YOK-99", "/tmp/099.md", "backlog", "yoke")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format(orphans, [], [], "detect")
        output = captured.getvalue()
        assert "HC-missing-gh-issues|Missing GitHub issues|WARN|" in output

    def test_warn_on_epic_task_orphans(self):
        orphans = [("1246/task-001", "epic_tasks:1246/1", "epic_task", "yoke")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format(orphans, [], [], "detect")
        output = captured.getvalue()
        assert "HC-orphan-epic-tasks|Orphan epic tasks|WARN|" in output

    def test_warn_on_gh_orphans(self):
        gh_orphans = [(999, "[YOK-999] Orphan", "OPEN", "yoke")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], gh_orphans, [], "detect")
        output = captured.getvalue()
        assert "HC-reverse-completeness|Reverse completeness|WARN|" in output

    def test_fix_mode_shows_fixed_in_detail(self):
        """Fix mode includes 'FIXED' in detail text."""
        drifts = [DriftRecord("YOK-42", "title", "Local", "GitHub")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], drifts, "fix")
        output = captured.getvalue()
        assert "FIXED" in output

    def test_hc_lines_parseable(self):
        """Each HC line has pipe-separated format with valid status."""
        drifts = [
            DriftRecord("YOK-1", "title", "a", "b"),
            DriftRecord("YOK-2", "body", "<local>", "<github>"),
            DriftRecord("YOK-3", "state", "CLOSED", "OPEN"),
            DriftRecord("YOK-4", "label-status", "status:done", "status:idea"),
        ]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], drifts, "detect")
        for line in captured.getvalue().strip().split("\n"):
            if line.startswith("HC-"):
                parts = line.split("|")
                assert len(parts) >= 3, f"HC line has <3 pipe fields: {line}"
                assert parts[2] in ("PASS", "WARN", "FAIL"), f"Bad status: {parts[2]}"
