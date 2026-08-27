"""Tests for merge_worktree: sync-local-target behaviour.

Other merge_worktree tests live in test_merge_worktree.py,
test_merge_worktree_locks.py, and test_merge_worktree_views.py.

Pytest fixture (mw_db) shared via _merge_worktree_test_helpers (private module).
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from yoke_core.engines import merge_worktree
from yoke_core.engines.merge_worktree import MergeArgs, MergeContext

from runtime.api.engines._merge_worktree_test_helpers import mw_db  # noqa: F401


class TestSyncLocalTarget:
    """_sync_local_target must
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
        """Successful fetch + matching refs → True (target
        not checked out — uses git fetch origin main:main)."""
        sha = "abc1234567890"


        def fake_run_git(cmd, cwd=None, capture=False, timeout=None):
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
        """Successful fetch + ff-only merge with matching refs → True
        (target checked out — uses git fetch then git merge --ff-only
        origin/{target}, not git pull)."""
        sha = "abc1234567890"


        def fake_run_git(cmd, cwd=None, capture=False, timeout=None):
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
        """Failed sync → returns False."""

        def fake_run_git(cmd, cwd=None, capture=False, timeout=None):
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            if cmd[0] == "rev-parse" and len(cmd) > 1 and cmd[1] == "--abbrev-ref":
                result.stdout = "YOK-9999"
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is False

    def test_ref_mismatch_returns_false(self, sync_ctx, monkeypatch):
        """Sync succeeds but local/origin refs differ → False."""

        def fake_run_git(cmd, cwd=None, capture=False, timeout=None):
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
        """Timeout during sync → returns False.

        The runner turns a timed-out git subprocess into a failed result
        carrying the reason, so the sync reads it like any other failure
        instead of unwinding through an exception.
        """
        from yoke_cli.config import credentialed_git

        def fake_run_git(cmd, cwd=None, capture=False, timeout=None):
            timed_out = cmd[0] == "fetch"
            result = mock.Mock()
            result.returncode = (
                credentialed_git.TIMEOUT_EXIT_CODE if timed_out else 0
            )
            result.stdout = ""
            result.stderr = "did not finish within 120s" if timed_out else ""
            if cmd[0] == "rev-parse" and len(cmd) > 1 and cmd[1] == "--abbrev-ref":
                result.stdout = "YOK-9999"
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is False

    def test_stash_restored_on_dirty_tree(self, sync_ctx, monkeypatch):
        """Dirty files are stashed before sync and restored after."""
        sha = "abc123"
        stash_ops = []
        first_status = {"called": False}


        def fake_run_git(cmd, cwd=None, capture=False, timeout=None):
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

    def test_sync_fetches_through_the_credentialed_runner(
        self, sync_ctx, monkeypatch
    ):
        """The fetch must reach the remote through ``_run_git``.

        A bare subprocess here would run on whatever credentials the calling
        shell happens to carry, which is nothing on a freshly onboarded
        machine. Routing it through the runner is what attaches the stored
        GitHub credential; the environment itself is the runner's own
        contract, pinned in ``test_merge_worktree``.
        """
        sha = "abc1234567890"
        seen: list[list[str]] = []

        def fake_run_git(cmd, cwd=None, capture=False, timeout=None):
            seen.append(list(cmd))
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
        assert ["fetch", "origin", "main:main"] in seen, seen

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
