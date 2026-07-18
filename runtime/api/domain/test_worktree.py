"""Tests for yoke_core.domain.worktree — pure parsers and path resolvers.

The original module covered every flavor of the Pythonized worktree lifecycle.
It is now split across sibling files so each authored file stays under the
350-line limit. ``create_worktree`` + ``resolve_item_worktree`` integration
coverage lives in ``test_worktree_create``, and ``detect_deps`` lives in
``test_worktree_deps``. Heavy fixture/helper code lives in
``worktree_test_helpers``.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from yoke_core.domain.worktree import (
    resolve_main_root,
    resolve_named_path,
    resolve_playwright_cache,
    resolve_yoke_root,
    resolve_worktree_root,
)
from yoke_core.domain import runtime_settings
from yoke_core.domain.worktree_create import _count_active_worktrees
from yoke_core.domain.worktree_deps import _find_nested
from yoke_core.domain.worktree_paths import _parse_item_id
from yoke_core.domain.worktree_test_helpers import (  # noqa: F401 — fixtures
    TEST_ITEM_ID,
    TEST_ITEM_REF,
    git_repo,
)


class TestParseItemId:
    def test_numeric(self):
        assert _parse_item_id(str(TEST_ITEM_ID)) == TEST_ITEM_ID

    def test_sun_prefix(self):
        assert _parse_item_id(TEST_ITEM_REF) == TEST_ITEM_ID

    def test_sun_prefix_lowercase(self):
        assert _parse_item_id("yok-55") == 55

    def test_leading_zeros(self):
        assert _parse_item_id("042") == 42

    def test_invalid(self):
        assert _parse_item_id("abc") is None

    def test_empty(self):
        assert _parse_item_id("") is None


class TestReadConfig:
    def test_reads_key(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text("base_branch=develop\nwip_cap=3\n")
        assert (
            runtime_settings.get_str("base_branch", "main", config_path=cfg)
            == "develop"
        )

    def test_default_on_missing(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text("wip_cap=3\n")
        assert (
            runtime_settings.get_str("base_branch", "main", config_path=cfg)
            == "main"
        )

    def test_default_on_missing_file(self, tmp_path):
        assert (
            runtime_settings.get_str(
                "key", "default", config_path=tmp_path / "nonexistent",
            )
            == "default"
        )

    def test_ignores_comments(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.write_text("# comment\nbase_branch=develop\n")
        assert (
            runtime_settings.get_str("base_branch", "", config_path=cfg)
            == "develop"
        )


class TestResolvePlaywrightCache:
    def test_with_project(self):
        result = resolve_playwright_cache("externalwebapp", "/some/worktree")
        assert result.endswith(".yoke/playwright-cache/externalwebapp")

    def test_without_project(self):
        result = resolve_playwright_cache(None, "/tmp/wt")
        assert result == "/tmp/wt/.playwright-cache"

    def test_no_args(self):
        assert resolve_playwright_cache(None, None) is None

    def test_empty_strings(self):
        assert resolve_playwright_cache("", "") is None


class TestResolvePaths:
    def test_main_root_from_worktree(self, git_repo):
        subprocess.run(
            ["git", "worktree", "add", str(git_repo / ".worktrees" / "YOK-1"), "-b", "YOK-1", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        worktree_path = str(git_repo / ".worktrees" / "YOK-1")
        assert resolve_main_root(cwd=worktree_path) == str(git_repo)

    def test_worktree_root_from_worktree(self, git_repo):
        subprocess.run(
            ["git", "worktree", "add", str(git_repo / ".worktrees" / "YOK-2"), "-b", "YOK-2", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        worktree_path = str(git_repo / ".worktrees" / "YOK-2")
        assert resolve_worktree_root(cwd=worktree_path) == worktree_path

    def test_named_paths(self, git_repo):
        assert resolve_named_path("main-file", ".yoke/lint-config", cwd=str(git_repo)) == str(git_repo / ".yoke" / "lint-config")
        assert resolve_named_path("backups", cwd=str(git_repo)) == str(git_repo / ".yoke" / "backups")

    def test_db_path_refuses_retired_sqlite_authority(self, git_repo):
        with pytest.raises(RuntimeError) as excinfo:
            resolve_named_path("db", cwd=str(git_repo))
        msg = str(excinfo.value)
        assert "SQLite authority retired/guarded" in msg
        assert "YOKE_PG_DSN" in msg
        assert str(git_repo / ".yoke" / "yoke.db") in msg

    def test_yoke_root_strips_worktree_from_env(self, git_repo):
        subprocess.run(
            ["git", "worktree", "add", str(git_repo / ".worktrees" / "YOK-3"), "-b", "YOK-3", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        worktree_state = git_repo / ".worktrees" / "YOK-3" / ".yoke"
        assert resolve_yoke_root(yoke_root_env=str(worktree_state)) == str(git_repo / ".yoke")


class TestFindNested:
    def test_finds_at_depth_1(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "package.json").write_text("{}")
        assert _find_nested(str(tmp_path), "package.json") is not None

    def test_respects_max_depth(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "package.json").write_text("{}")
        # max_depth=3 means we look at depth 0,1,2,3 — d is depth 4
        assert _find_nested(str(tmp_path), "package.json", max_depth=3) is None

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text("{}")
        assert _find_nested(str(tmp_path), "package.json") is None


class TestCountActiveWorktrees:
    def test_counts_correctly(self, git_repo):
        wt_dir = str(git_repo / ".worktrees")
        os.makedirs(wt_dir, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", os.path.join(wt_dir, "YOK-1"), "-b", "YOK-1", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "worktree", "add", os.path.join(wt_dir, "YOK-2"), "-b", "YOK-2", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        count, names = _count_active_worktrees(str(git_repo), wt_dir)
        assert count == 2
        assert set(names) == {"YOK-1", "YOK-2"}
