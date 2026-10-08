"""Tests for the delegated-sync doctor check."""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_delegated_sync,
)

from runtime.api.engines.test_doctor_git_github import (
    _make_completed,
    _make_conn,
    _self_project_is_yoke,  # noqa: F401 — pytest fixture
)


class TestHcDelegatedSync:
    """Tests for hc_delegated_sync (resync engine delegation)."""

    @patch("yoke_core.engines.doctor_report._run")
    def test_parses_doctor_format(self, mock_run):
        mock_run.return_value = _make_completed(
            stdout=(
                "HC-title-drift|Title drift|PASS|\n"
                "HC-body-drift|Body drift|WARN|YOK-1: body mismatch\n"
                "HC-missing-gh-issues|Missing GitHub issues|PASS|\n"
                "HC-orphan-epic-tasks|Orphan epic tasks|PASS|\n"
                "HC-reverse-completeness|Reverse completeness|PASS|\n"
                "HC-comment-sync|Comment sync|PASS|\n"
                "HC-label-drift|Label drift|PASS|\n"
                "HC-state-drift|State drift|PASS|\n"
                "HC-frozen-label-drift|Frozen label drift|PASS|\n"
                "HC-task-label-drift|Task label drift|PASS|\n"
            ),
        )
        conn = _make_conn()
        rec = RecordCollector()
        fn_args = DoctorArgs()
        hc_delegated_sync(conn, fn_args, rec)
        slugs = [r.check_id for r in rec.results]
        assert "HC-title-drift" in slugs
        assert "HC-body-drift" in slugs
        body_drift = [r for r in rec.results if r.check_id == "HC-body-drift"][0]
        assert body_drift.result == "WARN"

    @patch("yoke_core.engines.doctor_report._run")
    def test_fallback_on_no_output(self, mock_run):
        mock_run.return_value = _make_completed(returncode=2, stdout="")
        conn = _make_conn()
        rec = RecordCollector()
        fn_args = DoctorArgs()
        hc_delegated_sync(conn, fn_args, rec)
        assert all(r.result == "WARN" for r in rec.results)
        assert len(rec.results) == 11  # 10 + blocked-label-drift
