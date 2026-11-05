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

from runtime.api.engines._resync_full_test_helpers import (
    populated_db as populated_db,
    test_db as test_db,
)


class TestMainCLI:


    def test_detect_with_drifts_returns_1(self, populated_db):
        """Detect mode returns 1 when drifts found."""
        db_dir = os.path.dirname(populated_db)

        with (
            mock.patch(
                "yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir
            ),
            mock.patch(
                "yoke_core.engines.resync.stage1_linkage", return_value=([], [], [], {})
            ),
            mock.patch(
                "yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}
            ),
            mock.patch(
                "yoke_core.engines.resync.stage2_compare",
                return_value=[DriftRecord("YOK-1", "title", "a", "b")],
            ),
            mock.patch("sys.stdout", StringIO()),
        ):
            rc = main(["--detect-only", "--project", "yoke"])
        assert rc == 1


    def test_detect_doctor_format_with_drifts(self, test_db):
        """Detect + doctor-format with drifts emits HC lines."""
        db_dir = os.path.dirname(test_db)
        drifts = [
            DriftRecord("YOK-1", "title", "a", "b"),
            DriftRecord("YOK-2", "state", "CLOSED", "OPEN"),
        ]
        with (
            mock.patch(
                "yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir
            ),
            mock.patch(
                "yoke_core.engines.resync.stage1_linkage", return_value=([], [], [], {})
            ),
            mock.patch(
                "yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}
            ),
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
            mock.patch(
                "yoke_core.engines.resync._resolve_yoke_root", return_value=db_dir
            ),
            mock.patch(
                "yoke_core.engines.resync.stage1_linkage", return_value=([], [], [], {})
            ),
            mock.patch(
                "yoke_core.engines.resync.stage1_5_heavy_fetch", return_value={}
            ),
            mock.patch("yoke_core.engines.resync.stage2_compare", return_value=[]),
            mock.patch("sys.stdout", StringIO()) as captured,
        ):
            main(["--detect-only", "--project", "yoke"])
        output = captured.getvalue()
        assert "Summary:" in output
        assert "checked" in output
        assert "paired" in output
        assert "local-orphans" in output
        assert "github-orphans" in output
        assert "drifts" in output
