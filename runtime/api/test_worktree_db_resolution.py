"""Runtime path resolution from linked worktrees — regression tests.

Verifies ``resolve_yoke_root`` / ``resolve_named_path`` resolve from a
linked worktree without creating a worktree-local file DB. ``db`` mode
refuses retired file-DB authority.

Direct runtime-owner tests live in
``test_worktree_db_resolution_runtime_owners.py``. The shared
``fake_repo`` fixture lives in
``test_worktree_db_resolution_test_helpers``.
"""

from __future__ import annotations

from unittest import mock

import pytest

pytest_plugins = ("runtime.api.test_worktree_db_resolution_test_helpers",)


class TestResolveYokeRootBehavior:
    """Resolve_yoke_root returns .yoke/ and normalizes YOKE_ROOT."""

    def test_resolve_yoke_root_returns_project_yoke_dir(self, fake_repo):
        """resolve_yoke_root() returns {repo_root}/.yoke."""
        from yoke_core.domain.worktree import resolve_yoke_root

        with mock.patch(
            "yoke_core.domain.worktree_paths.resolve_main_root",
            return_value=str(fake_repo["main_root"]),
        ):
            result = resolve_yoke_root()

        assert result == str(fake_repo["main_root"] / ".yoke")

    def test_resolve_yoke_root_with_repo_root_env(self, fake_repo):
        """YOKE_ROOT pointing at repo root normalizes to .yoke/."""
        from yoke_core.domain.worktree import resolve_yoke_root

        result = resolve_yoke_root(
            yoke_root_env=str(fake_repo["main_root"]),
        )
        assert result == str(fake_repo["main_root"] / ".yoke")

    def test_resolve_yoke_root_with_project_yoke_env(self, fake_repo):
        """YOKE_ROOT pointing at .yoke/ returns .yoke/."""
        from yoke_core.domain.worktree import resolve_yoke_root

        state_path = str(fake_repo["main_root"] / ".yoke")
        result = resolve_yoke_root(yoke_root_env=state_path)
        assert result == state_path


class TestResolveNamedPathSplit:
    """Resolve_named_path splits state modes from content modes."""

    def test_state_modes_resolve_via_project_yoke_or_machine_config(
        self, fake_repo, monkeypatch
    ):
        """State modes resolve via .yoke/ or machine config."""
        from yoke_core.domain.worktree import resolve_named_path

        machine_cfg = fake_repo["main_root"] / ".machine-config.json"
        monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(machine_cfg))
        with mock.patch(
            "yoke_core.domain.worktree_paths.resolve_main_root",
            return_value=str(fake_repo["main_root"]),
        ):
            for mode, suffix in [
                ("config", ".machine-config.json"),
                ("config-example", ".machine-config.json"),
                ("board", ".yoke/BOARD.md"),
                ("backups", ".yoke/backups"),
            ]:
                result = resolve_named_path(mode)
                expected = str(fake_repo["main_root"] / suffix)
                assert result == expected, f"mode={mode}: {result} != {expected}"

    def test_content_modes_resolve_via_repo_root(self, fake_repo):
        """Content modes (docs, epics, ouroboros, etc.) resolve under repo root."""
        from yoke_core.domain.worktree import resolve_named_path

        with mock.patch(
            "yoke_core.domain.worktree_paths.resolve_main_root",
            return_value=str(fake_repo["main_root"]),
        ):
            for mode, suffix in [
                ("docs", "docs"),
                ("epics", "epics"),
                ("ouroboros", "ouroboros"),
                ("backlog", "backlog"),
            ]:
                result = resolve_named_path(mode)
                expected = str(fake_repo["main_root"] / suffix)
                assert result == expected, f"mode={mode}: {result} != {expected}"

    def test_db_mode_refuses_retired_file_authority(self, fake_repo):
        """db mode refuses a constructed file-DB path."""
        from yoke_core.domain.worktree import resolve_named_path

        with mock.patch(
            "yoke_core.domain.worktree_paths.resolve_main_root",
            return_value=str(fake_repo["main_root"]),
        ):
            with pytest.raises(RuntimeError) as exc:
                resolve_named_path("db")

        assert "SQLite authority retired/guarded" in str(exc.value)
