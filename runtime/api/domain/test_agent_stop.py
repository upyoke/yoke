"""Unit tests for yoke_core.domain.agent_stop — auto-commit + run_hook."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from yoke_core.domain.agent_stop import (
    AutoCommitResult,
    auto_commit_worktree,
    run_hook,
)
from yoke_core.domain.agent_stop_test_helpers import _init_git_repo


class TestAutoCommitWorktree:
    def test_empty_path_returns_empty_result(self):
        result = auto_commit_worktree("", "YOK-9999")
        assert result == AutoCommitResult()
        assert result.committed is False
        assert result.file_count == 0

    def test_nonexistent_path_returns_empty_result(self, tmp_path: Path):
        result = auto_commit_worktree(str(tmp_path / "missing"), "YOK-9999")
        assert result.committed is False

    def test_non_git_directory_returns_empty_result(self, tmp_path: Path):
        (tmp_path / "foo.txt").write_text("not a repo\n")
        result = auto_commit_worktree(str(tmp_path), "YOK-9999")
        assert result.committed is False

    def test_clean_worktree_is_noop(self, tmp_path: Path):
        _init_git_repo(tmp_path)
        result = auto_commit_worktree(str(tmp_path), "YOK-9999")
        assert result.committed is False
        assert result.file_count == 0

    def test_dirty_worktree_is_committed(self, tmp_path: Path):
        _init_git_repo(tmp_path)
        (tmp_path / "new-file.txt").write_text("dirty\n")

        result = auto_commit_worktree(str(tmp_path), "YOK-9999")

        assert result.committed is True
        assert result.file_count == 1
        log = subprocess.run(
            ["git", "-C", str(tmp_path), "log", "-1", "--pretty=%B"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "chore: auto-commit Engineer uncommitted work [YOK-9999]" in log.stdout
        assert "SubagentStop safety net" in log.stdout

    def test_multiple_files_recorded(self, tmp_path: Path):
        _init_git_repo(tmp_path)
        (tmp_path / "a.txt").write_text("a\n")
        (tmp_path / "b.txt").write_text("b\n")
        (tmp_path / "c.txt").write_text("c\n")

        result = auto_commit_worktree(str(tmp_path), "YOK-9999")

        assert result.committed is True
        assert result.file_count == 3
        for name in ("a.txt", "b.txt", "c.txt"):
            assert name in result.files

    def test_modified_file_is_staged_and_committed(self, tmp_path: Path):
        _init_git_repo(tmp_path)
        (tmp_path / "extra.txt").write_text("untracked\n")

        result = auto_commit_worktree(str(tmp_path), "YOK-99")

        assert result.committed is True
        assert result.file_count == 1
        assert "extra.txt" in result.files


class TestRunHook:
    def test_run_hook_swallows_exceptions(self):
        """Hook always exits 0 (never propagates exceptions)."""
        with patch(
            "runtime.harness.hook_helpers.find_project_root",
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise.
            run_hook()

    def test_run_hook_returns_early_when_db_missing(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        with patch(
            "runtime.harness.hook_helpers.resolve_yoke_db",
            return_value=str(tmp_path / "missing.db"),
        ), patch(
            "yoke_core.domain.agent_stop.process_dispatch_chains"
        ) as chains:
            run_hook()
        chains.assert_not_called()

    def test_run_hook_ignores_role_argument(self, tmp_path: Path, monkeypatch):
        """``--role`` is accepted but ignored — the gate it activated is gone."""
        db_path = tmp_path / "yoke.db"
        db_path.write_text("seed\n", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        with patch(
            "runtime.harness.hook_helpers.find_project_root",
            return_value=str(tmp_path),
        ), patch(
            "runtime.harness.hook_helpers.resolve_yoke_db",
            return_value=str(db_path),
        ), patch(
            "runtime.harness.hook_helpers.get_session_id",
            return_value="sess-1",
        ), patch(
            "yoke_core.domain.agent_stop.process_dispatch_chains",
        ) as chains, patch(
            "yoke_core.domain.agent_stop.emit_harness_session_stopped",
        ):
            run_hook(role="tester")

        # process_dispatch_chains signature no longer accepts role; verify
        # the wrapper does not forward one.
        assert "role" not in chains.call_args.kwargs
