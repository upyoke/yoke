"""Worktree-authority updates after done-transition cleanup."""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.engines import done_transition
from yoke_core.engines._done_transition_test_helpers import (
    _insert_item,
    dt_db as _shared_dt_db,
)
from runtime.api.engines.test_done_transition_post import _patch_run_internals


@pytest.fixture
def dt_db(tmp_path, monkeypatch):
    yield from _shared_dt_db.__wrapped__(tmp_path, monkeypatch)


class TestCleanupMetadata:
    def test_cleanup_refusal_preserves_worktree_authority(self, dt_db):
        db_path, _ = dt_db
        repo_root = db_path.parent
        _insert_item(db_path, 78, status="implemented", worktree="YOK-78")
        update = mock.Mock(return_value=0)

        with _patch_run_internals(
            repo_root,
            _cleanup_stale_branches=False,
            _update_item_direct=update,
        ):
            assert done_transition.run(78) == 0

        assert not any(
            call.args[1:3] == ("worktree", "null")
            for call in update.call_args_list
        )

    def test_completed_cleanup_clears_worktree_authority(self, dt_db):
        db_path, _ = dt_db
        repo_root = db_path.parent
        _insert_item(db_path, 79, status="implemented", worktree="YOK-79")
        update = mock.Mock(return_value=0)

        with _patch_run_internals(
            repo_root,
            _cleanup_stale_branches=True,
            _update_item_direct=update,
        ):
            assert done_transition.run(79) == 0

        assert any(
            call.args[1:3] == ("worktree", "null")
            for call in update.call_args_list
        )
