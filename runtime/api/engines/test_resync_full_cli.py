"""Tests for resync's main CLI (--detect/--fix/exit codes/doctor format).

Pytest fixtures (test_db, populated_db) are shared via
_resync_full_test_helpers (private module).
"""

# ruff: noqa: F811

from __future__ import annotations

import os
from io import StringIO
from unittest import mock

from yoke_core.engines.resync import DriftRecord, main

from yoke_core.engines._resync_full_test_helpers import (
    populated_db as populated_db,
    test_db as test_db,
)


class TestMainCLI:
    def test_unknown_flag_returns_1(self):
        """Unknown flag returns exit code 1."""
        with mock.patch("sys.stderr", StringIO()):
            rc = main(["--unknown"])
        assert rc == 1

    def test_detect_no_github_auth_fails_closed(self, test_db):
        """When the Yoke GitHub App auth is not configured, the engine fail-closes
        at the boundary with exit 2 + a repair hint -- the old
        SKIP-on-no-gh path has been retired.
        """
        from yoke_core.domain.project_github_auth import MissingCapability

        db_dir = os.path.dirname(test_db)
        with (
            mock.patch(
                "yoke_core.engines.resync_runtime.resolve_project_github_auth",
                side_effect=MissingCapability("yoke", "no capability"),
            ),
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
                side_effect=MissingCapability("yoke", "no capability"),
            ),
            mock.patch("yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir),
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()),
        ):
            rc = main(["--detect-only"])
        # Boundary translates the typed error to exit 2 (Yoke is the
        # control plane -- no SKIP path).
        assert rc == 2

    def test_detect_with_local_orphans_returns_1(self, populated_db):
        """Detect mode returns 1 when local orphans found."""
        db_dir = os.path.dirname(populated_db)

        def fake_linkage(db_path, yoke_root):
            return (
                [],
                [("YOK-99", "/tmp/099.md", "backlog", "yoke")],
                [],
                {},
            )

        with (
            mock.patch("yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir),
            mock.patch("yoke_core.engines.resync.stage1_linkage", fake_linkage),
            mock.patch("yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}),
            mock.patch("yoke_core.engines.resync.stage2_compare", return_value=[]),
            mock.patch("sys.stdout", StringIO()),
        ):
            rc = main(["--detect-only"])
        assert rc == 1

    def test_detect_with_drifts_returns_1(self, populated_db):
        """Detect mode returns 1 when drifts found."""
        db_dir = os.path.dirname(populated_db)

        with (
            mock.patch("yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir),
            mock.patch("yoke_core.engines.resync.stage1_linkage", return_value=([], [], [], {})),
            mock.patch("yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}),
            mock.patch(
                "yoke_core.engines.resync.stage2_compare",
                return_value=[DriftRecord("YOK-1", "title", "a", "b")],
            ),
            mock.patch("sys.stdout", StringIO()),
        ):
            rc = main(["--detect-only"])
        assert rc == 1

    def test_detect_no_drift_returns_0(self, test_db):
        """Detect mode returns 0 when no issues."""
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

    def test_fix_mode_no_failures_returns_0(self, test_db):
        """Fix mode returns 0 when no failures."""
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

    def test_detect_doctor_format_with_drifts(self, test_db):
        """Detect + doctor-format with drifts emits HC lines."""
        db_dir = os.path.dirname(test_db)
        drifts = [
            DriftRecord("YOK-1", "title", "a", "b"),
            DriftRecord("YOK-2", "state", "CLOSED", "OPEN"),
        ]
        with (
            mock.patch("yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir),
            mock.patch("yoke_core.engines.resync.stage1_linkage", return_value=([], [], [], {})),
            mock.patch("yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}),
            mock.patch("yoke_core.engines.resync.stage2_compare", return_value=drifts),
            mock.patch("sys.stdout", StringIO()) as captured,
        ):
            main(["--detect-only", "--doctor-format"])
        output = captured.getvalue()
        assert "HC-title-drift|Title drift|WARN|" in output
        assert "HC-state-drift|State drift|WARN|" in output

    def test_summary_line_format(self, test_db):
        """Summary line has expected format."""
        db_dir = os.path.dirname(test_db)
        with (
            mock.patch("yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir),
            mock.patch("yoke_core.engines.resync.stage1_linkage", return_value=([], [], [], {})),
            mock.patch("yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}),
            mock.patch("yoke_core.engines.resync.stage2_compare", return_value=[]),
            mock.patch("sys.stdout", StringIO()) as captured,
        ):
            main(["--detect-only"])
        output = captured.getvalue()
        assert "Summary:" in output
        assert "checked" in output
        assert "paired" in output
        assert "local-orphans" in output
        assert "github-orphans" in output
        assert "drifts" in output
