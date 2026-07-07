"""Runtime DB resolution from worktrees — runtime-owner regression tests.

Split from ``test_worktree_db_resolution.py``. Covers the AC-3 / AC-5
checks that runtime owner paths (service_client, engines, domain
helpers) all delegate to the canonical resolver and never create a
worktree-local yoke.db.
"""

from __future__ import annotations

import os
from unittest import mock

from yoke_core.domain import db_backend
# Re-export shared fixture.
from runtime.api.test_worktree_db_resolution_test_helpers import (  # noqa: F401
    fake_repo,
)


def _expected_path(fake_repo) -> str:
    return "" if db_backend.is_postgres() else str(fake_repo["main_db"])


class TestRuntimeOwnerFromWorktree:
    """AC-3/AC-5: runtime owners no longer carry bespoke parents[3] fallback."""

    def test_service_client_resolves_main_db(self, fake_repo):
        """service_client._get_db_path() delegates to canonical resolver."""
        from yoke_core.api.service_client import _get_db_path

        with mock.patch(
            "yoke_core.domain.db_helpers.resolve_db_path",
            return_value=str(fake_repo["main_db"]),
        ):
            result = _get_db_path()

        assert result == str(fake_repo["main_db"])
        stray = fake_repo["wt_data"] / "yoke.db"
        assert not stray.exists()

    def test_repair_status_resolves_main_db(self, fake_repo):
        """engines.repair_status._db_path() delegates to canonical resolver."""
        from yoke_core.engines.repair_status import _db_path

        with mock.patch(
            "yoke_core.domain.db_helpers.resolve_db_path",
            return_value=str(fake_repo["main_db"]),
        ):
            result = _db_path()

        assert result == str(fake_repo["main_db"])

    def test_done_transition_resolves_main_db(self, fake_repo):
        """engines.done_transition._db_path() delegates to canonical resolver."""
        from yoke_core.engines.done_transition import _db_path

        with mock.patch(
            "yoke_core.domain.db_helpers.resolve_db_path",
            return_value=str(fake_repo["main_db"]),
        ):
            result = _db_path()

        assert result == _expected_path(fake_repo)

    def test_merge_worktree_resolves_main_db(self, fake_repo):
        """engines.merge_worktree._db_path() delegates to canonical resolver."""
        from yoke_core.engines.merge_worktree import _db_path

        with mock.patch(
            "yoke_core.domain.db_helpers.resolve_db_path",
            return_value=str(fake_repo["main_db"]),
        ):
            result = _db_path()

        assert result == _expected_path(fake_repo)

    def test_merge_lock_resolves_main_db(self, fake_repo):
        """domain.merge_lock._db_path() delegates to canonical resolver."""
        from yoke_core.domain.merge_lock import _db_path

        with mock.patch(
            "yoke_core.domain.db_helpers.resolve_db_path",
            return_value=str(fake_repo["main_db"]),
        ):
            result = _db_path()

        assert result == _expected_path(fake_repo)

    def test_backup_resolves_main_db(self, fake_repo):
        """domain.backup._resolve_db_path() delegates to canonical resolver."""
        from yoke_core.domain.backup import _resolve_db_path

        with mock.patch(
            "yoke_core.domain.db_helpers.resolve_db_path",
            return_value=str(fake_repo["main_db"]),
        ):
            result = _resolve_db_path()

        assert result == str(fake_repo["main_db"])

    def test_emit_event_resolves_main_db(self, fake_repo):
        """domain.emit_event._db_path() delegates to canonical resolver."""
        from yoke_core.domain.emit_event import _db_path

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YOKE_DB", None)
            os.environ.pop("YOKE_ROOT", None)
            with mock.patch(
                "yoke_core.domain.db_helpers.resolve_db_path",
                return_value=str(fake_repo["main_db"]),
            ):
                result = _db_path()

        assert result == str(fake_repo["main_db"])

    def test_events_resolves_main_db(self, fake_repo):
        """domain.events._resolve_db_path() delegates to canonical resolver."""
        from yoke_core.domain.events import _resolve_db_path

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YOKE_DB", None)
            os.environ.pop("YOKE_ROOT", None)
            with mock.patch(
                "yoke_core.domain.db_helpers.resolve_db_path",
                return_value=str(fake_repo["main_db"]),
            ):
                result = _resolve_db_path()

        assert result == str(fake_repo["main_db"])

    def test_backlog_write_path_resolves_main_db(self, fake_repo):
        """domain.backlog._resolve_write_db_path() delegates to canonical resolver."""
        from yoke_core.domain.backlog import _resolve_write_db_path

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YOKE_DB", None)
            os.environ.pop("YOKE_ROOT", None)
            with mock.patch(
                "yoke_core.domain.db_helpers.resolve_db_path",
                return_value=str(fake_repo["main_db"]),
            ):
                result = _resolve_write_db_path()

        assert result == _expected_path(fake_repo)

    def test_backlog_write_path_falls_back_for_missing_db(self, fake_repo):
        """backlog write path keeps the main-repo target even before the DB exists."""
        from yoke_core.domain.backlog import _resolve_write_db_path

        fake_repo["main_db"].unlink()
        stray = fake_repo["wt_data"] / "yoke.db"
        assert not fake_repo["main_db"].exists()
        assert not stray.exists()

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YOKE_DB", None)
            os.environ.pop("YOKE_ROOT", None)
            with mock.patch(
                "yoke_core.domain.db_helpers.resolve_db_path",
                side_effect=FileNotFoundError("missing main DB for write path"),
            ), mock.patch(
                "yoke_core.domain.worktree_paths.resolve_db_path",
                return_value=str(fake_repo["main_db"]),
            ) as resolver:
                result = _resolve_write_db_path()

        assert result == _expected_path(fake_repo)
        if not db_backend.is_postgres():
            resolver.assert_called_once()
        assert not stray.exists()

    def test_schema_resolves_main_db_even_when_missing_for_init(self, fake_repo):
        """schema._resolve_db_path() must keep the main-repo target even
        before init has created the DB file."""
        from yoke_core.domain.schema import _resolve_db_path

        fake_repo["main_db"].unlink()
        stray = fake_repo["wt_data"] / "yoke.db"
        assert not fake_repo["main_db"].exists()
        assert not stray.exists()

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YOKE_DB", None)
            os.environ.pop("YOKE_ROOT", None)
            with mock.patch(
                "yoke_core.domain.db_helpers.resolve_db_path",
                side_effect=FileNotFoundError("missing main DB for init"),
            ), mock.patch(
                "yoke_core.domain.worktree.resolve_db_path",
                return_value=str(fake_repo["main_db"]),
            ) as resolver:
                result = _resolve_db_path()

        assert result == _expected_path(fake_repo)
        if not db_backend.is_postgres():
            resolver.assert_called_once()
        assert not stray.exists()

    def test_epic_task_sync_resolves_main_db(self, fake_repo):
        """domain.epic_task_sync._db_path() delegates to canonical resolver."""
        from yoke_core.domain.epic_task_sync import _db_path

        with mock.patch(
            "yoke_core.domain.db_helpers.resolve_db_path",
            return_value=str(fake_repo["main_db"]),
        ):
            result = _db_path()

        assert result == str(fake_repo["main_db"])

    def test_update_status_yoke_root_normalizes_both_env_shapes(self, fake_repo):
        """domain.update_status._yoke_root() accepts repo-root and state-dir
        YOKE_ROOT values but always returns the canonical state dir."""
        from yoke_core.domain.update_status import _yoke_root

        expected = fake_repo["main_root"] / ".yoke"
        with mock.patch.dict(os.environ, {"YOKE_ROOT": str(fake_repo["main_root"])}, clear=False):
            assert _yoke_root() == expected
        with mock.patch.dict(os.environ, {"YOKE_ROOT": str(expected)}, clear=False):
            assert _yoke_root() == expected

    def test_epic_task_sync_yoke_root_normalizes_both_env_shapes(self, fake_repo):
        """domain.epic_task_sync._yoke_root() accepts repo-root and state-dir
        YOKE_ROOT values but always returns the canonical state dir."""
        from yoke_core.domain.epic_task_sync import _yoke_root

        expected = fake_repo["main_root"] / ".yoke"
        with mock.patch.dict(os.environ, {"YOKE_ROOT": str(fake_repo["main_root"])}, clear=False):
            assert _yoke_root() == expected
        with mock.patch.dict(os.environ, {"YOKE_ROOT": str(expected)}, clear=False):
            assert _yoke_root() == expected

    def test_service_client_normalize_yoke_root_accepts_both_shapes(self, fake_repo):
        """service_client helper normalizes repo-root and state-dir inputs to
        the same canonical ``.yoke/`` path."""
        from yoke_core.api.service_client import _normalize_yoke_root

        expected = (fake_repo["main_root"] / ".yoke").resolve()
        assert _normalize_yoke_root(str(fake_repo["main_root"])) == expected
        assert _normalize_yoke_root(str(expected)) == expected
