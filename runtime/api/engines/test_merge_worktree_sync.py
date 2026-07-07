"""Tests for merge_worktree: sync-local-target behaviour.

Other merge_worktree tests live in test_merge_worktree.py,
test_merge_worktree_locks.py, and test_merge_worktree_views.py.

Pytest fixture (mw_db) shared via _merge_worktree_test_helpers (private module).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.engines import merge_worktree
from yoke_core.engines.merge_worktree import MergeArgs, MergeContext

from yoke_core.engines._merge_worktree_test_helpers import mw_db


class TestSyncLocalTarget:
    """AC-2/AC-3/AC-5/AC-7/AC-8/AC-9: _sync_local_target must
    use git fetch origin {target}:{target} for branch-agnostic ref update
    and return a bool success signal."""

    @pytest.fixture
    def sync_ctx(self, tmp_path, monkeypatch):
        """Build a MergeContext suitable for _sync_local_target tests."""
        ctx = MergeContext(args=MergeArgs(branch="YOK-9999", target="main"))
        ctx.repo_root = str(tmp_path)
        ctx.yoke_repo_root = str(tmp_path)
        ctx.item_id = "9999"
        ctx.epic_id = None
        # Silence prints
        monkeypatch.setattr(merge_worktree, "_print", lambda *a, **kw: None)
        return ctx

    def test_success_returns_true_not_checked_out(self, sync_ctx, monkeypatch):
        """AC-2/AC-5: successful fetch + matching refs → True (target
        not checked out — uses git fetch origin main:main)."""
        sha = "abc1234567890"

        def fake_run(
            cmd,
            cwd=None,
            capture_output=False,
            text=False,
            timeout=None,
            env=None,
        ):
            return mock.Mock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_run_git(cmd, cwd=None, capture=False):
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            if cmd[0] == "status":
                result.stdout = ""  # clean tree
            elif cmd[0] == "rev-parse" and len(cmd) > 1:
                if cmd[1] == "--abbrev-ref":
                    result.stdout = "YOK-9999"  # NOT on main
                elif cmd[1] == "main":
                    result.stdout = sha
                elif cmd[1] == "origin/main":
                    result.stdout = sha
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is True

    def test_success_returns_true_checked_out(self, sync_ctx, monkeypatch):
        """AC-2/AC-5: successful fetch + ff-only merge with matching refs → True
        (target checked out — uses git fetch then git merge --ff-only
        origin/{target}, not git pull)."""
        sha = "abc1234567890"

        def fake_run(
            cmd,
            cwd=None,
            capture_output=False,
            text=False,
            timeout=None,
            env=None,
        ):
            return mock.Mock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_run_git(cmd, cwd=None, capture=False):
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            if cmd[0] == "status":
                result.stdout = ""
            elif cmd[0] == "rev-parse" and len(cmd) > 1:
                if cmd[1] == "--abbrev-ref":
                    result.stdout = "main"  # ON main
                elif cmd[1] == "main":
                    result.stdout = sha
                elif cmd[1] == "origin/main":
                    result.stdout = sha
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is True

    def test_fetch_failure_returns_false(self, sync_ctx, monkeypatch):
        """AC-3/AC-8: failed sync → returns False."""
        def fake_run(
            cmd,
            cwd=None,
            capture_output=False,
            text=False,
            timeout=None,
            env=None,
        ):
            return mock.Mock(returncode=1, stdout="", stderr="non-fast-forward")

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_run_git(cmd, cwd=None, capture=False):
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            if cmd[0] == "rev-parse" and len(cmd) > 1 and cmd[1] == "--abbrev-ref":
                result.stdout = "YOK-9999"
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is False

    def test_ref_mismatch_returns_false(self, sync_ctx, monkeypatch):
        """AC-7: sync succeeds but local/origin refs differ → False."""
        def fake_run(
            cmd,
            cwd=None,
            capture_output=False,
            text=False,
            timeout=None,
            env=None,
        ):
            return mock.Mock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_run_git(cmd, cwd=None, capture=False):
            result = mock.Mock()
            result.returncode = 0
            if cmd[0] == "status":
                result.stdout = ""
            elif cmd[0] == "rev-parse" and len(cmd) > 1:
                if cmd[1] == "--abbrev-ref":
                    result.stdout = "YOK-9999"
                elif cmd[1] == "main":
                    result.stdout = "aaa111"
                elif cmd[1] == "origin/main":
                    result.stdout = "bbb222"
                else:
                    result.stdout = ""
            else:
                result.stdout = ""
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is False

    def test_timeout_returns_false(self, sync_ctx, monkeypatch):
        """Timeout during sync → returns False."""
        import subprocess as sp

        def fake_run(
            cmd,
            cwd=None,
            capture_output=False,
            text=False,
            timeout=None,
            env=None,
        ):
            raise sp.TimeoutExpired(cmd, timeout or 120)

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_run_git(cmd, cwd=None, capture=False):
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            if cmd[0] == "rev-parse" and len(cmd) > 1 and cmd[1] == "--abbrev-ref":
                result.stdout = "YOK-9999"
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is False

    def test_stash_restored_on_dirty_tree(self, sync_ctx, monkeypatch):
        """AC-9: dirty files are stashed before sync and restored after."""
        sha = "abc123"
        stash_ops = []
        first_status = {"called": False}

        def fake_run(
            cmd,
            cwd=None,
            capture_output=False,
            text=False,
            timeout=None,
            env=None,
        ):
            return mock.Mock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_run_git(cmd, cwd=None, capture=False):
            result = mock.Mock()
            result.returncode = 0
            if cmd[0] == "status" and not first_status["called"]:
                first_status["called"] = True
                result.stdout = "M  dirty.py\n"
            elif cmd[0] == "stash" and cmd[1] == "push":
                stash_ops.append("push")
                result.stdout = ""
            elif cmd[0] == "stash" and cmd[1] == "pop":
                stash_ops.append("pop")
                result.stdout = ""
            elif cmd[0] == "rev-parse" and len(cmd) > 1:
                if cmd[1] == "--abbrev-ref":
                    result.stdout = "YOK-9999"
                elif cmd[1] == "main":
                    result.stdout = sha
                elif cmd[1] == "origin/main":
                    result.stdout = sha
                else:
                    result.stdout = ""
            else:
                result.stdout = ""
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        result = merge_worktree._sync_local_target(sync_ctx)
        assert result is True
        assert stash_ops == ["push", "pop"]

    def test_sync_uses_noninteractive_git_env(self, sync_ctx, monkeypatch):
        sha = "abc1234567890"
        seen_env = {}

        def fake_run(
            cmd,
            cwd=None,
            capture_output=False,
            text=False,
            timeout=None,
            env=None,
        ):
            seen_env["value"] = env
            return mock.Mock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_run_git(cmd, cwd=None, capture=False):
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            if cmd[0] == "status":
                result.stdout = ""
            elif cmd[0] == "rev-parse" and len(cmd) > 1:
                if cmd[1] == "--abbrev-ref":
                    result.stdout = "YOK-9999"
                elif cmd[1] == "main":
                    result.stdout = sha
                elif cmd[1] == "origin/main":
                    result.stdout = sha
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is True
        assert seen_env["value"]["GIT_TERMINAL_PROMPT"] == "0"
        assert seen_env["value"]["GCM_INTERACTIVE"] == "Never"
        assert seen_env["value"]["GIT_SSH_COMMAND"] == "ssh -oBatchMode=yes"

    def test_source_uses_fetch_or_ff_only_not_rebase(self):
        """Regression guard: _sync_local_target must not use pull --rebase
        and must never reach for ``git pull`` in the checked-out path. It
        uses ``git fetch`` plus ``git merge --ff-only`` (for the checked-out
        target) or a single ``git fetch`` ref update (for the non-checked-out
        target), but never ``--rebase`` and never ``git pull``."""
        import ast

        from yoke_core.engines import (
            merge_worktree_local_sync,
            merge_worktree_post,
            merge_worktree_post_helpers,
        )
        # _sync_local_target now lives in merge_worktree_local_sync; the
        # other modules re-export the symbol for legacy import paths.
        source = (
            Path(merge_worktree_post.__file__).read_text()
            + "\n"
            + Path(merge_worktree_post_helpers.__file__).read_text()
            + "\n"
            + Path(merge_worktree_local_sync.__file__).read_text()
        )
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_sync_local_target":
                func_source = ast.get_source_segment(source, node) or ""
                assert '"--rebase"' not in func_source, (
                    "_sync_local_target must not use --rebase"
                )
                assert '"pull"' not in func_source, (
                    "_sync_local_target must not use git pull; the checked-out "
                    "path must use git fetch + git merge --ff-only to avoid "
                    "multi-branch fast-forward ambiguity."
                )
                assert '"fetch"' in func_source
                assert '"--ff-only"' in func_source
                assert '"merge"' in func_source, (
                    "_sync_local_target must use git merge --ff-only on the "
                    "checked-out target path."
                )
                break
        else:
            pytest.fail("_sync_local_target function not found in source")
