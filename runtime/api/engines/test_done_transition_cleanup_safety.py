"""Fail-closed done-transition cleanup regressions."""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.engines import done_transition, done_transition_cleanup
from yoke_core.engines._done_transition_test_helpers import dt_db as _shared_dt_db
from runtime.api.test_backlog import _seed_claim


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


@pytest.fixture
def dt_db(tmp_path, monkeypatch):
    yield from _shared_dt_db.__wrapped__(tmp_path, monkeypatch)


class TestCleanupStaleBranches:
    def test_uses_terminal_lane_helper(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        with (
            mock.patch.object(done_transition, "_run_git") as run_git,
            mock.patch.object(
                done_transition_cleanup, "prune_landed_lane", return_value=()
            ) as shared,
        ):
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # valid branch
                mock.Mock(returncode=0, stdout="abc\n"),  # local branch
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, TEST_ITEM_REF, project_repo
            )

        assert complete is True
        shared.assert_called_once()
        assert shared.call_args.kwargs["branch"] == TEST_ITEM_REF
        assert shared.call_args.kwargs["target"] == "main"

    def test_shared_refusal_is_advisory(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        with (
            mock.patch.object(done_transition, "_run_git") as run_git,
            mock.patch.object(
                done_transition_cleanup,
                "prune_landed_lane",
                return_value=("dirty worktree preserved",),
            ),
        ):
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),
                mock.Mock(returncode=0, stdout="abc\n"),
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, TEST_ITEM_REF, project_repo
            )
        assert complete is False

    def test_unexpected_shared_cleanup_error_is_advisory(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        with (
            mock.patch.object(done_transition, "_run_git") as run_git,
            mock.patch.object(
                done_transition_cleanup,
                "prune_landed_lane",
                side_effect=RuntimeError("cleanup transport unavailable"),
            ),
        ):
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),
                mock.Mock(returncode=0, stdout="abc\n"),
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, TEST_ITEM_REF, project_repo
            )

        assert complete is False

    def test_invalid_worktree_field_stops_before_fetch(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.return_value = mock.Mock(returncode=1, stdout="")
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, "../other-worktree", project_repo
            )

        assert complete is False
        assert run_git.call_count == 1
        assert "check-ref-format" in run_git.call_args.args[0]

    def test_foreign_claim_preserves_entire_lane(self, dt_db, tmp_path):
        db_path, _ = dt_db
        _seed_claim(
            db_path,
            session_id="other-session",
            item_id=str(TEST_ITEM_ID),
        )
        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        assert done_transition_cleanup._has_foreign_claim(TEST_ITEM_ID)

        with mock.patch.object(done_transition, "_run_git") as run_git:
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID,
                TEST_ITEM_REF,
                project_repo,
                authority_block="another session held the item claim",
            )

        assert complete is False
        run_git.assert_not_called()


class TestDoneRunnerCleanupIsAdvisory:
    def test_incomplete_cleanup_does_not_block_done(self, dt_db):
        db_path, _ = dt_db
        from yoke_core.engines._done_transition_test_helpers import _insert_item

        repo_root = db_path.parent
        _insert_item(db_path, TEST_ITEM_ID, status="reviewed-implementation")

        from runtime.api.engines.test_done_transition_post import (
            _patch_run_internals,
        )

        timeline: list[str] = []
        cleanup = mock.Mock(
            side_effect=lambda *_a, **_kw: timeline.append("cleanup") or False
        )
        update_done = mock.Mock(
            side_effect=lambda *_a, **_kw: timeline.append("done") or True
        )
        with _patch_run_internals(
            repo_root,
            _cleanup_stale_branches=cleanup,
            _update_status_to_done=update_done,
        ):
            rc = done_transition.run(TEST_ITEM_ID)

        assert rc == 0
        cleanup.assert_called_once()
        update_done.assert_called_once()
        assert timeline == ["done", "cleanup"]
