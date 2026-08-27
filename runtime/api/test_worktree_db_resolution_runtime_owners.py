"""Runtime DB resolution from worktrees — runtime-owner regression tests.

Runtime owners open Postgres through ``db_helpers.connect`` and never
create a worktree-local file DB. Path-token helpers return empty or
refuse; they do not construct a file path.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from yoke_core.domain import db_backend

pytest_plugins = ("runtime.api.test_worktree_db_resolution_test_helpers",)


class TestRuntimeOwnerFromWorktree:
    """Runtime owners no longer carry bespoke parents[3] fallback."""

    def test_service_client_path_token_refuses_file_authority(self, fake_repo):
        """service_client._get_db_path() refuses a constructed file path."""
        from yoke_core.api.service_client import _get_db_path

        with pytest.raises(RuntimeError, match="Postgres authority"):
            _get_db_path()
        stray = fake_repo["wt_data"] / "yoke.db"
        assert not stray.exists()

    def test_repair_status_connects_via_canonical_helper(self, fake_repo):
        """engines.repair_status._connect() delegates to db_helpers.connect."""
        from yoke_core.engines.repair_status import _connect

        sentinel = object()
        with mock.patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=sentinel,
        ):
            result = _connect()

        assert result is sentinel
        stray = fake_repo["wt_data"] / "yoke.db"
        assert not stray.exists()

    def test_done_transition_path_token_is_empty(self, fake_repo):
        """engines.done_transition._db_path() returns the empty token."""
        from yoke_core.engines.done_transition import _db_path

        assert _db_path() == ""
        assert not (fake_repo["wt_data"] / "yoke.db").exists()

    def test_merge_worktree_path_token_is_empty(self, fake_repo):
        """engines.merge_worktree._db_path() returns the empty token."""
        from yoke_core.engines.merge_worktree import _db_path

        assert _db_path() == ""
        assert not (fake_repo["wt_data"] / "yoke.db").exists()

    def test_merge_lock_path_token_is_empty(self, fake_repo):
        """domain.merge_lock._db_path() returns the empty token."""
        from yoke_core.domain.merge_lock import _db_path

        assert _db_path() == ""
        assert not (fake_repo["wt_data"] / "yoke.db").exists()

    def test_backup_path_token_refuses_file_authority(self, fake_repo):
        """domain.backup._resolve_db_path() refuses a constructed file path."""
        from yoke_core.domain.backup import _resolve_db_path

        with pytest.raises(RuntimeError, match="Postgres authority"):
            _resolve_db_path()

    def test_emit_event_path_token_is_absent(self, fake_repo):
        """domain.emit_event._db_path() returns None."""
        from yoke_core.domain.emit_event import _db_path

        assert _db_path() is None

    def test_events_path_token_is_absent(self, fake_repo):
        """domain.events._resolve_db_path() returns None."""
        from yoke_core.domain.events import _resolve_db_path

        assert _resolve_db_path() is None

    def test_backlog_write_path_token_is_empty(self, fake_repo):
        """domain.backlog._resolve_write_db_path() returns the empty token."""
        from yoke_core.domain.backlog import _resolve_write_db_path

        assert _resolve_write_db_path() == ""
        assert not (fake_repo["wt_data"] / "yoke.db").exists()

    def test_schema_path_token_is_empty(self, fake_repo):
        """schema._resolve_db_path() returns the empty token."""
        from yoke_core.domain.schema import _resolve_db_path

        assert _resolve_db_path() == ""
        assert not (fake_repo["wt_data"] / "yoke.db").exists()

    def test_epic_task_sync_path_token_is_empty(self, fake_repo):
        """domain.epic_task_sync._db_path() returns the empty token."""
        from yoke_core.domain.epic_task_sync import _db_path

        assert _db_path() == ""

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

    def test_postgres_authority_does_not_need_file_db(self, fake_repo):
        if not db_backend.is_postgres():
            return
        assert db_backend.is_postgres()
        assert not (fake_repo["wt_data"] / "yoke.db").exists()
