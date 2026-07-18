"""Tests for merge_worktree: state-dir resolution and view regeneration.

Other merge_worktree tests live in test_merge_worktree.py,
test_merge_worktree_locks.py, and test_merge_worktree_sync.py.

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


class TestYokeStateDirResolution:
    """AC-1, AC-2, AC-3: Yoke artifact dir must be distinct from both
    the project repo root and the Yoke control-repo root, and the
    non-``yoke`` project case must preserve the distinction."""

    def _make_yoke_control_repo(self, tmp_path: Path) -> Path:
        """Create a minimal Yoke control-repo layout so rebuild_board's
        resolve_main_repo_root() walks to the right root."""
        control = tmp_path / "runtime"
        (control / "runtime" / "backlog").mkdir(parents=True)
        return control

    def test_state_dir_is_yoke_subdir_of_control_repo(self, tmp_path):
        control = self._make_yoke_control_repo(tmp_path)
        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"))
        ctx.repo_root = str(control)
        ctx.yoke_repo_root = str(control)

        state_dir = merge_worktree._yoke_state_dir(ctx)
        assert state_dir == control / ".yoke"
        # Explicitly NOT the control-repo root.
        assert state_dir != Path(ctx.yoke_repo_root)

    def test_state_dir_for_non_yoke_project(self, tmp_path):
        """AC-3: when ctx.repo_root is rewritten to a project repo, the
        Yoke state dir is still derived from ctx.yoke_repo_root (the
        Yoke control-repo root), not from ctx.repo_root."""
        control = self._make_yoke_control_repo(tmp_path)
        project_repo = tmp_path / "externalwebapp"
        project_repo.mkdir()

        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"))
        ctx.repo_root = str(project_repo)  # non-yoke project
        ctx.yoke_repo_root = str(control)  # Yoke control repo

        state_dir = merge_worktree._yoke_state_dir(ctx)
        # Artifact dir lives under the Yoke control repo, NOT the project repo.
        assert state_dir == control / ".yoke"
        assert project_repo not in state_dir.parents

    def test_state_dir_strips_worktree_path(self, tmp_path):
        """When entered from inside a ``.worktrees/YOK-N`` worktree,
        ``_yoke_state_dir`` must resolve to the main control repo's
        state dir, matching rebuild_board's internal stripping."""
        control = self._make_yoke_control_repo(tmp_path)
        worktree_path = control / ".worktrees" / "YOK-9999"
        worktree_path.mkdir(parents=True)

        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"))
        ctx.repo_root = str(worktree_path)
        ctx.yoke_repo_root = str(worktree_path)

        state_dir = merge_worktree._yoke_state_dir(ctx)
        # Stripped back to the main control repo's artifact dir.
        assert state_dir == control / ".yoke"


class TestRegenerateViewsTargetsStateDir:
    """AC-1, AC-4: _regenerate_views targets the Yoke control repo
    and invokes board.rebuild.run through a subprocess."""

    def _make_yoke_control_repo(self, tmp_path: Path) -> Path:
        control = tmp_path / "runtime"
        (control / "runtime" / "backlog").mkdir(parents=True)
        return control

    def test_regenerate_views_passes_repo_root_to_board(self, tmp_path, monkeypatch):
        """backlog_md retired — only board rebuild remains."""
        control = self._make_yoke_control_repo(tmp_path)
        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"))
        ctx.repo_root = str(control)
        ctx.yoke_repo_root = str(control)

        captured = {}

        def fake_run(module, args, **kwargs):
            captured["module"] = module
            captured["args"] = list(args)
            return mock.Mock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(merge_worktree, "_run_python_module", fake_run)

        merge_worktree._regenerate_views(ctx)

        assert captured["module"] == "yoke_core.domain.rebuild_board"
        assert "--force" in captured["args"]
        assert str(control) in captured["args"]

    def test_regenerate_views_non_yoke_project_board(self, tmp_path, monkeypatch):
        """non-yoke project — board rebuild targets control repo."""
        control = self._make_yoke_control_repo(tmp_path)
        project_repo = tmp_path / "externalwebapp"
        project_repo.mkdir()

        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"))
        ctx.repo_root = str(project_repo)
        ctx.yoke_repo_root = str(control)

        captured = {}

        def fake_run(module, args, **kwargs):
            captured["args"] = list(args)
            return mock.Mock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(merge_worktree, "_run_python_module", fake_run)

        merge_worktree._regenerate_views(ctx)

        assert str(control) in captured["args"]


class TestRegenerateViewsExitCode5:
    """AC-5, AC-6: _regenerate_views_or_exit5 catches
    post-merge-cleanup failures and returns exit code 5 with a precise
    MergeEngineFailed event (phase=post_merge_cleanup, merge_committed=true)."""

    def test_success_returns_0(self, tmp_path, monkeypatch):
        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"))
        ctx.repo_root = str(tmp_path)
        ctx.yoke_repo_root = str(tmp_path)
        ctx.item_id = "9999"

        monkeypatch.setattr(
            merge_worktree, "_regenerate_views", lambda _c: None
        )

        emitted = []
        monkeypatch.setattr(
            merge_worktree,
            "_emit_merge_event",
            lambda name, **kw: emitted.append((name, kw)),
        )

        exit_code = merge_worktree._regenerate_views_or_exit5(ctx)
        assert exit_code == 0
        # No failure event on success.
        assert not any(name == "MergeEngineFailed" for name, _ in emitted)

    def test_failure_returns_5_with_precise_event(self, tmp_path, monkeypatch):
        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"))
        ctx.repo_root = str(tmp_path)
        ctx.yoke_repo_root = str(tmp_path)
        ctx.item_id = "9999"
        ctx.epic_id = None

        def _boom(_ctx):
            raise FileNotFoundError("simulated missing backlog dir")

        monkeypatch.setattr(merge_worktree, "_regenerate_views", _boom)

        emitted = []
        monkeypatch.setattr(
            merge_worktree,
            "_emit_merge_event",
            lambda name, **kw: emitted.append((name, kw)),
        )

        exit_code = merge_worktree._regenerate_views_or_exit5(ctx)

        assert exit_code == 5

        # Exactly one precise MergeEngineFailed event — structured.
        failed = [kw for name, kw in emitted if name == "MergeEngineFailed"]
        assert len(failed) == 1
        ctx_kw = failed[0]["context"]
        assert ctx_kw["phase"] == "post_merge_cleanup"
        assert ctx_kw["merge_committed"] is True
        assert ctx_kw["exit_code"] == 5
        assert ctx_kw["error_type"] == "FileNotFoundError"
        assert "simulated missing backlog dir" in ctx_kw["error"]
        assert failed[0]["severity"] == "ERROR"
        assert failed[0]["outcome"] == "failure"
        assert failed[0]["item_id"] == "9999"


class TestMergeWorktreeNoLegacyBugPattern:
    """AC-9: regression guard — the literal ``Path(ctx.yoke_repo_root) / "backlog"``
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
        for mod in (merge_worktree, merge_worktree_prepare, merge_worktree_execute,
                    merge_worktree_post, merge_worktree_post_helpers):
            sources.append(Path(mod.__file__).read_text())
        return "\n".join(sources)

    def test_no_literal_bug_pattern_in_source(self):
        source = self._all_engine_sources()
        # The exact buggy expression.
        assert 'Path(ctx.yoke_repo_root) / "backlog"' not in source
        # Variations that would also collapse the state dir.
        assert "ctx.yoke_repo_root + '/backlog'" not in source
        assert 'ctx.yoke_repo_root + "/backlog"' not in source

    def test_source_references_state_dir_helper(self):
        source = self._all_engine_sources()
        # The helper must exist. backlog_dir no longer used.
        assert "def _yoke_state_dir(ctx: MergeContext)" in source


# ---------------------------------------------------------------------------
# resolve_context uses resolve_main_root (not rev-parse)
# ---------------------------------------------------------------------------


class TestResolveContextUsesMainRoot:
    """AC-1/AC-4/AC-6: resolve_context must call resolve_main_root
    to get ctx.repo_root, so that invoking from a worktree CWD still
    resolves to the main repo root."""

    def test_resolve_context_uses_resolve_main_root(self, mw_db, tmp_path, monkeypatch):
        """AC-4/AC-6: ctx.repo_root resolves to the main repo, not
        the worktree, when resolve_main_root returns the main root."""
        main_root = tmp_path / "main-repo"
        main_root.mkdir()

        monkeypatch.setattr(
            "yoke_core.domain.worktree.resolve_main_root",
            lambda: str(main_root),
        )
        monkeypatch.setenv("YOKE_DONE_TRANSITION", "1")
        # Stub git calls that happen after repo_root is set
        monkeypatch.setattr(
            merge_worktree, "_run_git",
            lambda cmd, cwd=None, capture=False: mock.Mock(
                returncode=0, stdout="", stderr="",
            ),
        )

        args = MergeArgs(branch="YOK-99")
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
