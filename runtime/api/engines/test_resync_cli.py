"""Resync engine: doctor-format output, CLI, and exit-code tests.

Pytest fixtures (test_db, populated_db) are shared via
_resync_test_helpers (private module).
"""

from __future__ import annotations

import json
import os
import sys
from io import StringIO
from unittest import mock

import pytest

from yoke_core.engines.resync import (
    DriftRecord,
    _emit_doctor_format,
    main,
    stage2_compare,
)

from yoke_core.engines._resync_test_helpers import (
    populated_db,
    test_db,
)


class TestDoctorFormat:
    def test_all_pass_when_no_issues(self, test_db):
        """Doctor format shows PASS for all HCs when no issues found."""
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], [], "detect")

        output = captured.getvalue()
        assert "HC-missing-gh-issues|Missing GitHub issues|PASS|" in output
        assert "HC-title-drift|Title drift|PASS|" in output
        assert "HC-body-drift|Body drift|PASS|" in output
        assert "HC-state-drift|State drift|PASS|" in output
        assert "HC-label-drift|Label drift|PASS|" in output

    def test_warn_on_title_drift(self, test_db):
        """Doctor format shows WARN for title drift."""
        drifts = [DriftRecord("YOK-42", "title", "Local Title", "GitHub Title")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], drifts, "detect")

        output = captured.getvalue()
        assert "HC-title-drift|Title drift|WARN|" in output
        assert "YOK-42" in output

    def test_warn_on_local_orphans(self, test_db):
        """Doctor format shows WARN for local orphans."""
        orphans = [("YOK-99", "/tmp/099.md", "backlog", "yoke")]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format(orphans, [], [], "detect")

        output = captured.getvalue()
        assert "HC-missing-gh-issues|Missing GitHub issues|WARN|" in output

    def test_hc_lines_are_parseable(self, test_db):
        """Each HC line has exactly the pipe-separated format."""
        drifts = [
            DriftRecord("YOK-1", "title", "a", "b"),
            DriftRecord("YOK-2", "body", "<local body>", "<github body>"),
            DriftRecord("YOK-3", "state", "CLOSED", "OPEN"),
        ]
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _emit_doctor_format([], [], drifts, "detect")

        for line in captured.getvalue().strip().split("\n"):
            if line.startswith("HC-"):
                parts = line.split("|")
                assert len(parts) >= 3, f"HC line has <3 pipe fields: {line}"
                assert parts[2] in ("PASS", "WARN", "FAIL"), f"Bad status: {parts[2]}"


class TestMainCLI:
    def test_unknown_flag_returns_1(self):
        """Unknown flag returns exit code 1."""
        with mock.patch("sys.stderr", StringIO()):
            rc = main(["--unknown"])
        assert rc == 1

    def test_db_path_missing_value_returns_1(self):
        """The Doctor/test db-path compatibility flag requires a value."""
        with mock.patch("sys.stderr", StringIO()):
            rc = main(["--detect-only", "--db-path"])
        assert rc == 1

    def test_detect_defaults_to_ambient_authority_token(self, test_db):
        """Default Postgres authority should not invent a yoke.db path."""
        db_dir = os.path.dirname(test_db)
        observed: dict[str, str] = {}

        def fake_linkage(db_path, yoke_root):
            observed["db_path"] = db_path
            observed["yoke_root"] = yoke_root
            return ([], [], [], {})

        with (
            mock.patch("yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir),
            mock.patch("yoke_core.engines.resync.stage1_linkage", fake_linkage),
            mock.patch("yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}),
            mock.patch("yoke_core.engines.resync.stage2_compare", return_value=[]),
            mock.patch("sys.stdout", StringIO()),
        ):
            rc = main(["--detect-only"])

        assert rc == 0
        assert observed == {"db_path": "", "yoke_root": db_dir}

    def test_db_path_is_accepted_and_forwarded(self, test_db):
        """Doctor may pass a backend token; resync must not reject it."""
        db_dir = os.path.dirname(test_db)
        observed: dict[str, str] = {}

        def fake_linkage(db_path, yoke_root):
            observed["db_path"] = db_path
            observed["yoke_root"] = yoke_root
            return ([], [], [], {})

        with (
            mock.patch("yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir),
            mock.patch("yoke_core.engines.resync.stage1_linkage", fake_linkage),
            mock.patch("yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}),
            mock.patch("yoke_core.engines.resync.stage2_compare", return_value=[]),
            mock.patch("sys.stdout", StringIO()),
        ):
            rc = main(["--detect-only", "--doctor-format", "--db-path", "/tmp/doctor.db"])

        assert rc == 0
        assert observed == {"db_path": "/tmp/doctor.db", "yoke_root": db_dir}

    def test_detect_no_pat_fails_closed(self, test_db):
        """When the Yoke PAT is not configured, the engine fail-closes
        with exit 2 + repair hint (Yoke is the control plane -- the
        legacy SKIP-on-no-gh path has been retired).
        """
        from yoke_core.domain.project_github_auth import MissingCapability

        db_dir = os.path.dirname(test_db)

        with (
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
                side_effect=MissingCapability("yoke", "no capability"),
            ),
            mock.patch(
                "yoke_core.engines.resync._resolve_yoke_root",
                return_value=db_dir,
            ),
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()),
        ):
            rc = main(["--detect-only"])

        assert rc == 2

    def test_detect_no_pat_doctor_format_fails_closed(self, test_db):
        """Same fail-closed semantics under --doctor-format."""
        from yoke_core.domain.project_github_auth import MissingCapability

        db_dir = os.path.dirname(test_db)

        with (
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
                side_effect=MissingCapability("yoke", "no capability"),
            ),
            mock.patch(
                "yoke_core.engines.resync._resolve_yoke_root",
                return_value=db_dir,
            ),
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()),
        ):
            rc = main(["--detect-only", "--doctor-format"])

        assert rc == 2

    def test_detect_with_drifts_returns_1(self, populated_db):
        """Detect mode returns 1 when drifts are found."""
        db_dir = os.path.dirname(populated_db)

        def fake_linkage(db_path, yoke_root):
            return (
                [],  # paired
                [("YOK-99", "/tmp/099.md", "backlog", "yoke")],  # local orphans
                [],  # gh orphans
                {},  # gh_by_project
            )

        with (
            mock.patch("yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir),
            mock.patch("yoke_core.engines.resync.stage1_linkage", fake_linkage),
            mock.patch("yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}),
            mock.patch("yoke_core.engines.resync.stage2_compare", return_value=[]),
            mock.patch("sys.stdout", StringIO()),
        ):
            rc = main(["--detect-only"])

        assert rc == 1  # local orphan = drift


class TestDriftRecord:
    def test_to_pipe(self):
        d = DriftRecord("YOK-42", "title", "local", "github")
        assert d.to_pipe() == "YOK-42|title|local|github"


class TestExitCodes:
    def test_exit_0_on_no_drift_detect(self, test_db):
        """Exit 0 when no drifts in detect mode."""
        # test_db already lives in tmp_path -- use its parent as yoke_root
        db_dir = os.path.dirname(test_db)

        with (
            mock.patch("yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir),
            mock.patch("yoke_core.engines.resync.stage1_linkage", return_value=([], [], [], {})),
            mock.patch("yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}),
            mock.patch("yoke_core.engines.resync.stage2_compare", return_value=[]),
            mock.patch("sys.stdout", StringIO()),
        ):
            rc = main(["--detect-only"])

        assert rc == 0

    def test_exit_0_on_fix_success(self, test_db):
        """Exit 0 when fix mode with no failures."""
        db_dir = os.path.dirname(test_db)

        with (
            mock.patch("yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir),
            mock.patch("yoke_core.engines.resync.stage1_linkage", return_value=([], [], [], {})),
            mock.patch("yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}),
            mock.patch("yoke_core.engines.resync.stage2_compare", return_value=[]),
            mock.patch("sys.stdout", StringIO()),
        ):
            rc = main(["--fix"])

        assert rc == 0
