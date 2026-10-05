"""Doctor identifies disposable scratch residue and preserves durable state."""

import os
import time
from unittest.mock import patch
from yoke_core.engines.doctor import hc_orphaned_temp_files
from runtime.api.engines.test_doctor_git_worktrees import _run_hc


class TestHcOrphanedTempFiles:
    """Tests for hc_orphaned_temp_files.

    The scanner enumerates known kind directories across the global
    project/session/run tree. Each test isolates that tree via
    ``YOKE_SCRATCH_ROOT``.
    """

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    def test_no_temp_files_passes(self, mock_root, tmp_path, monkeypatch):
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        rec = _run_hc(hc_orphaned_temp_files)
        assert rec.results[0].result == "PASS"

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    def test_stale_ephemeral_residue_warns(self, mock_root, tmp_path, monkeypatch):
        # Preserves the legacy 300s (ephemeral residue) threshold: a
        # stale watcher-captures file older than 300s warns.
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        captures_dir = (
            tmp_path
            / "other"
            / "sessions"
            / "past"
            / "runs"
            / "old"
            / "watcher-captures"
        )
        captures_dir.mkdir(parents=True)
        stale_file = captures_dir / "yoke-pytest.raw.abc.log"
        stale_file.write_text("")
        old_epoch = int(time.time()) - 3600
        os.utime(stale_file, (old_epoch, old_epoch))

        rec = _run_hc(hc_orphaned_temp_files)
        assert rec.results[0].result == "WARN"
        assert "yoke-pytest.raw.abc.log" in rec.results[0].detail
        assert "kind=watcher-captures" in rec.results[0].detail

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    def test_unknown_durable_storage_is_preserved(
        self, mock_root, tmp_path, monkeypatch
    ):
        # Durable storage is not one generic disposable bucket. Unknown helper
        # state stays intact until its owner has an explicit cleanup contract.
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        storage_dir = (
            tmp_path
            / "other"
            / "sessions"
            / "past"
            / "runs"
            / "old"
            / "storage"
            / "db_error_hook"
        )
        storage_dir.mkdir(parents=True)
        stale_file = storage_dir / "collapse-state-stale.json"
        stale_file.write_text("{}")
        old_epoch = int(time.time()) - 3600
        os.utime(stale_file, (old_epoch, old_epoch))
        os.utime(storage_dir, (old_epoch, old_epoch))

        rec = _run_hc(hc_orphaned_temp_files)
        assert rec.results[0].result == "PASS"
        assert stale_file.read_text(encoding="utf-8") == "{}"

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    def test_fresh_residue_passes(self, mock_root, tmp_path, monkeypatch):
        # An ephemeral residue file under the 300s threshold should not
        # warn — the scanner respects the per-sub-directory threshold.
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        captures_dir = (
            tmp_path
            / "other"
            / "sessions"
            / "past"
            / "runs"
            / "old"
            / "watcher-captures"
        )
        captures_dir.mkdir(parents=True)
        fresh_file = captures_dir / "yoke-pytest.raw.fresh.log"
        fresh_file.write_text("")
        # mtime ~now() means age < 300s — under the ephemeral threshold.
        rec = _run_hc(hc_orphaned_temp_files)
        assert rec.results[0].result == "PASS"
