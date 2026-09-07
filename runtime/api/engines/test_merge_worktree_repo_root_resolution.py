# ruff: noqa: F401, F811
"""Tests for merge_worktree repo-root resolution.
Other merge_worktree tests live in test_merge_worktree.py,
test_merge_worktree_locks.py, and test_merge_worktree_sync.py.

Pytest fixture (mw_db) shared via _merge_worktree_test_helpers (private module).
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from yoke_core.engines import merge_worktree
from yoke_core.engines.merge_worktree import MergeArgs, MergeContext

from runtime.api.engines._merge_worktree_test_helpers import mw_db


class TestMergeWorktreeNoLegacyBugPattern:
    """Regression guard — the literal ``Path(ctx.yoke_repo_root) / "backlog"``
    pattern must not reappear in the engine.  Any future refactor that
    re-introduces it reopens the 2026-04-11 incident."""

    def _all_engine_sources(self):
        """Collect source text from parent + child modules."""
        from yoke_core.engines import (
            merge_worktree_prepare,
            merge_worktree_execute,
            merge_worktree_post,
            merge_worktree_post_helpers,
        )

        sources = []
        for mod in (
            merge_worktree,
            merge_worktree_prepare,
            merge_worktree_execute,
            merge_worktree_post,
            merge_worktree_post_helpers,
        ):
            sources.append(Path(mod.__file__).read_text())
        return "\n".join(sources)

    def test_no_literal_bug_pattern_in_source(self):
        source = self._all_engine_sources()
        # The exact buggy expression.
        assert 'Path(ctx.yoke_repo_root) / "backlog"' not in source
        # Variations that would also collapse the state dir.
        assert "ctx.yoke_repo_root + '/backlog'" not in source
        assert 'ctx.yoke_repo_root + "/backlog"' not in source


# ---------------------------------------------------------------------------
# resolve_context uses resolve_main_root (not rev-parse)
# ---------------------------------------------------------------------------


class TestResolveContextUsesMainRoot:
    """Resolve_context must call resolve_main_root
    to get ctx.repo_root, so that invoking from a worktree CWD still
    resolves to the main repo root."""

    def test_resolve_context_uses_resolve_main_root(self, mw_db, tmp_path, monkeypatch):
        """Ctx.repo_root resolves to the main repo, not
        the worktree, when resolve_main_root returns the main root."""
        main_root = tmp_path / "main-repo"
        main_root.mkdir()

        monkeypatch.setattr(
            "yoke_core.domain.worktree.resolve_main_root",
            lambda: str(main_root),
        )
        # Stub git calls that happen after repo_root is set
        monkeypatch.setattr(
            merge_worktree,
            "_run_git",
            lambda cmd, cwd=None, capture=False: mock.Mock(
                returncode=0,
                stdout="",
                stderr="",
            ),
        )

        args = MergeArgs(branch="YOK-99", standalone=True)
        ctx = merge_worktree.resolve_context(args)

        assert ctx.repo_root == str(main_root)
        assert ctx.yoke_repo_root == str(main_root)

    def test_resolve_context_raises_on_no_repo(self, mw_db, monkeypatch):
        """resolve_context raises RuntimeError when not in a git repo."""
        monkeypatch.setattr(
            "yoke_core.domain.worktree.resolve_main_root",
            mock.Mock(side_effect=RuntimeError("not in git")),
        )

        with pytest.raises(RuntimeError, match="Not in a git repository"):
            merge_worktree.resolve_context(MergeArgs(branch="YOK-99"))

    def test_source_does_not_use_rev_parse_show_toplevel(self):
        """Regression guard: resolve_context must not use
        git rev-parse --show-toplevel for repo root resolution."""
        import ast

        from yoke_core.engines import merge_worktree_prepare

        source = Path(merge_worktree_prepare.__file__).read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "resolve_context":
                func_source = ast.get_source_segment(source, node) or ""
                assert "rev-parse" not in func_source, (
                    "resolve_context must use resolve_main_root, not "
                    "git rev-parse --show-toplevel"
                )
                assert "resolve_main_root" in func_source
                break
        else:
            pytest.fail("resolve_context function not found in source")


# ---------------------------------------------------------------------------
# _sync_local_target branch-agnostic ref update
# ---------------------------------------------------------------------------
