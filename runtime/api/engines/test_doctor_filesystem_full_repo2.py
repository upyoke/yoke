"""Doctor filesystem HC tests: repo file health checks (part B).

Continuation of test_doctor_filesystem_full_repo.py.

Schema scaffolding shared via _doctor_filesystem_full_test_helpers (private module).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yoke_core.engines.doctor import (
    RecordCollector,
    _resolve_main_root,
    _resolve_repo_root,
    hc_arch_consistency,
    hc_browser_substrate,
    hc_claudemd_drift,
    hc_config_validation,
    hc_stray_db,
    hc_stray_project_files,
)

from yoke_core.engines._doctor_filesystem_full_test_helpers import (
    _args,
    _cp,
    _make_conn,
    _run_hc,
)


class TestRepoFileHealthChecksB:
    """Continuation of TestRepoFileHealthChecks (split for size)."""

    def test_stray_project_files_pass_when_clean(self, tmp_path):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_stray_project_files)
        assert rec.results[0].result == "PASS"

    # ---- expanded HC-stray-db scope ---------------------------------

    def test_stray_db_passes_when_no_strays(self, tmp_path):
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)
        ), patch(
            "yoke_core.engines.doctor_report._resolve_main_root", return_value=str(tmp_path)
        ):
            rec = _run_hc(hc_stray_db)
        assert rec.results[0].result == "PASS"

    def test_stray_db_warns_on_worktree_local_stray_nonempty(self, tmp_path):
        """A non-empty stray ``.worktrees/<branch>/.../yoke.db`` must
        surface as WARN with Postgres-native review-and-remove guidance —
        no migrate-into-data/yoke.db instruction, because the control
        plane is Postgres and there is no authoritative SQLite file."""
        stray = tmp_path / ".worktrees" / "YOK-999" / "runtime" / "yoke.db"
        stray.parent.mkdir(parents=True)
        stray.write_text("fake-nonempty-payload")
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)
        ), patch(
            "yoke_core.engines.doctor_report._resolve_main_root", return_value=str(tmp_path)
        ):
            rec = _run_hc(hc_stray_db)
        assert rec.results[0].result == "WARN"
        detail = rec.results[0].detail
        assert ".worktrees/YOK-999/runtime/yoke.db" in detail
        assert "Postgres" in detail
        assert "stray file" in detail
        # The obsolete "migrate into data/yoke.db" guidance is gone.
        assert "migrate" not in detail.lower()

    def test_stray_db_deletes_empty_worktree_stray_with_fix(self, tmp_path):
        """empty strays are safe to auto-delete under ``--fix``."""
        stray = tmp_path / ".worktrees" / "YOK-9999" / "runtime" / "yoke.db"
        stray.parent.mkdir(parents=True)
        stray.write_text("")
        assert stray.exists()

        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)
        ), patch(
            "yoke_core.engines.doctor_report._resolve_main_root", return_value=str(tmp_path)
        ):
            rec = _run_hc(hc_stray_db, fix=True)

        assert rec.results[0].result == "PASS"
        assert not stray.exists()

    def test_stray_db_refuses_nonempty_stray_even_with_fix(self, tmp_path):
        """A non-empty stray is never auto-deleted, not even under
        ``--fix``. Yoke's control plane is Postgres, so doctor cannot
        know whether the SQLite file holds anything the operator still
        wants; it emits WARN and leaves the file in place for manual
        review rather than migrating or deleting it."""
        stray = tmp_path / ".worktrees" / "YOK-9999" / "runtime" / "yoke.db"
        stray.parent.mkdir(parents=True)
        stray.write_text("real-data-do-not-touch")
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)
        ), patch(
            "yoke_core.engines.doctor_report._resolve_main_root", return_value=str(tmp_path)
        ):
            rec = _run_hc(hc_stray_db, fix=True)

        assert rec.results[0].result == "WARN"
        assert stray.exists()
        assert stray.read_text() == "real-data-do-not-touch"

    def test_browser_substrate_warns_when_chromium_missing(self, tmp_path):
        browser_dir = tmp_path / "browser-runtime"
        browser_dir.mkdir(parents=True)
        (browser_dir / "package.json").write_text("{}")
        (browser_dir / "node_modules").mkdir()
        with patch(
            "yoke_core.domain.browser_runtime_home.runtime_dir", return_value=browser_dir
        ), patch(
            "yoke_core.engines.doctor_report._run", return_value=_cp(returncode=1, stdout="")
        ):
            rec = _run_hc(hc_browser_substrate)
        assert rec.results[0].result == "WARN"
        assert "Chromium binary not found" in rec.results[0].detail

    def test_browser_substrate_warns_when_not_materialized(self, tmp_path):
        with patch(
            "yoke_core.domain.browser_runtime_home.runtime_dir",
            return_value=tmp_path / "browser-runtime",
        ):
            rec = _run_hc(hc_browser_substrate)
        assert rec.results[0].result == "WARN"
        assert "not materialized" in rec.results[0].detail
