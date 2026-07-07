"""Runtime DB resolution from linked worktrees — regression tests.

Verifies that both the unified resolver layer (db_helpers.resolve_db_path) and
``resolve_yoke_root`` / ``resolve_named_path`` resolve from a linked worktree
without creating a worktree-local yoke.db.

The local project state dir is now ``.yoke/`` and machine-global config lives
under ``~/.yoke/config.json``. Tests below verify that ``resolve_yoke_root``
returns ``{repo}/.yoke``, ``resolve_db_path`` refuses retired file DB
authority, and ``resolve_named_path`` splits project-local state modes from
content modes under the repo root.

Direct runtime-owner delegation tests (service_client, engines, etc.)
live in ``test_worktree_db_resolution_runtime_owners.py``. The shared
``fake_repo`` fixture lives in
``test_worktree_db_resolution_test_helpers``.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from yoke_core.domain import db_backend
# Re-export shared fixture.
from runtime.api.test_worktree_db_resolution_test_helpers import (  # noqa: F401
    fake_repo,
)


class TestUnifiedResolverFromWorktree:
    """AC-2: CLI invocation from inside a linked worktree resolves main-repo DB."""

    def test_db_helpers_resolves_main_db_from_worktree(self, fake_repo):
        """db_helpers.resolve_db_path() returns main-repo DB when called from
        worktree context."""
        from yoke_core.domain.db_helpers import resolve_db_path

        # Mock the worktree resolver to simulate being inside the worktree
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YOKE_DB", None)
            os.environ.pop("YOKE_ROOT", None)
            with mock.patch(
                "yoke_core.domain.worktree_paths.resolve_db_path",
                return_value=str(fake_repo["main_db"]),
            ):
                if db_backend.is_postgres():
                    with pytest.raises(RuntimeError, match="Postgres authority"):
                        resolve_db_path()
                    assert not (
                        fake_repo["wt_data"] / "yoke.db"
                    ).exists()
                    return
                result = resolve_db_path()

        assert result == str(fake_repo["main_db"])
        # Worktree-local DB must NOT have been created
        stray = fake_repo["wt_data"] / "yoke.db"
        assert not stray.exists(), f"Stray DB created at {stray}"


class TestResolveYokeRootBehavior:
    """AC-2/AC-4: resolve_yoke_root returns .yoke/ and normalizes YOKE_ROOT."""

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

    def test_resolve_db_path_refuses_retired_file_authority(self, fake_repo):
        """resolve_db_path() refuses the retired project-local yoke.db path."""
        from yoke_core.domain.worktree import resolve_db_path

        retired_path = fake_repo["main_root"] / ".yoke" / "yoke.db"
        with mock.patch(
            "yoke_core.domain.worktree_paths.resolve_main_root",
            return_value=str(fake_repo["main_root"]),
        ):
            with pytest.raises(RuntimeError) as exc:
                resolve_db_path()

        message = str(exc.value)
        assert "SQLite authority retired/guarded" in message
        assert str(retired_path) in message

class TestResolveNamedPathSplit:
    """AC-3: resolve_named_path splits state modes from content modes."""

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
                ("designs", "designs"),
                ("backlog", "backlog"),
            ]:
                result = resolve_named_path(mode)
                expected = str(fake_repo["main_root"] / suffix)
                assert result == expected, f"mode={mode}: {result} != {expected}"

    def test_db_mode_refuses_retired_file_authority(self, fake_repo):
        """db mode refuses the retired project-local yoke.db path."""
        from yoke_core.domain.worktree import resolve_named_path

        retired_path = fake_repo["main_root"] / ".yoke" / "yoke.db"
        with mock.patch(
            "yoke_core.domain.worktree_paths.resolve_main_root",
            return_value=str(fake_repo["main_root"]),
        ):
            with pytest.raises(RuntimeError) as exc:
                resolve_named_path("db")

        message = str(exc.value)
        assert "SQLite authority retired/guarded" in message
        assert str(retired_path) in message


class TestNoStrayDbCreation:
    """AC-1: advance from main repo does not create worktree-local yoke.db."""

    def test_no_stray_db_after_resolution(self, fake_repo):
        """Simulates the advance lifecycle: resolve DB from worktree context,
        verify no stray file is created."""
        from yoke_core.domain.db_helpers import resolve_db_path

        wt_stray = fake_repo["wt_data"] / "yoke.db"
        assert not wt_stray.exists(), "Precondition: no stray before test"

        # Simulate resolution from worktree context (what happens during advance)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YOKE_DB", None)
            os.environ.pop("YOKE_ROOT", None)
            with mock.patch(
                "yoke_core.domain.worktree_paths.resolve_db_path",
                return_value=str(fake_repo["main_db"]),
            ):
                if db_backend.is_postgres():
                    with pytest.raises(RuntimeError, match="Postgres authority"):
                        resolve_db_path()
                    assert not wt_stray.exists()
                    return
                db_path = resolve_db_path()

        # The resolved path must be the main DB, not the worktree
        assert db_path == str(fake_repo["main_db"])
        assert not wt_stray.exists(), "Stray DB must not be created during resolution"
