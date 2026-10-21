"""Trial-branch cleanup behavior for completed backlog items."""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.engines import done_transition
from runtime.api.engines._done_transition_test_helpers import (
    _insert_item,
    dt_db as _shared_dt_db,
)


@pytest.fixture
def dt_db(tmp_path, monkeypatch):
    yield from _shared_dt_db.__wrapped__(tmp_path, monkeypatch)


class TestCleanupTrialBranches:
    def test_deletes_only_merged_trial_for_done_item(self, dt_db, tmp_path):
        db_path, _ = dt_db
        _insert_item(db_path, 99, status="done")
        project_repo = tmp_path / "repo"
        project_repo.mkdir()

        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout="  trial/YOK-99\n"),
                mock.Mock(returncode=0, stdout=""),  # ancestry
                mock.Mock(returncode=0, stdout=""),  # branch -D
            ]
            assert done_transition._cleanup_trial_branches(project_repo) is True

        # The delete is forced because it carries the shared landing proof,
        # which is the reading git's own ``-d`` safety cannot make: a trial
        # ref replayed onto HEAD keeps its own commits and would survive.
        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert any("branch -D trial/YOK-99" in command for command in commands)

    def test_preserves_trial_branch_for_active_item(self, dt_db, tmp_path):
        db_path, _ = dt_db
        _insert_item(db_path, 100, status="implementing")
        project_repo = tmp_path / "repo"
        project_repo.mkdir()

        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.return_value = mock.Mock(returncode=0, stdout="  trial/YOK-100\n")
            assert done_transition._cleanup_trial_branches(project_repo) is False

        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert not any(
            "branch -d" in command or "branch -D" in command for command in commands
        )

    def test_preserves_non_item_trial_branch(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.return_value = mock.Mock(
                returncode=0, stdout="  trial/abandoned-feature\n"
            )
            done_transition._cleanup_trial_branches(project_repo)

        assert run_git.call_count == 1

    def test_sweep_deletes_merged_trial_in_another_project(self, dt_db, tmp_path):
        db_path, _ = dt_db
        # EXT-5 is item 900; reading the 5 as items.id would miss the item.
        _insert_item(
            db_path,
            900,
            status="done",
            project="externalwebapp",
            project_sequence=5,
            worktree="EXT-5",
        )
        project_repo = tmp_path / "repo"
        project_repo.mkdir()

        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout="  trial/EXT-5\n"),
                mock.Mock(returncode=0, stdout=""),  # ancestry
                mock.Mock(returncode=0, stdout=""),  # branch -D
            ]
            assert done_transition._cleanup_trial_branches(project_repo) is True

        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert any("branch -D trial/EXT-5" in command for command in commands)

    def test_item_cleanup_lists_the_items_own_lane_names(self, dt_db, tmp_path):
        db_path, _ = dt_db
        _insert_item(
            db_path, 600, status="done", project_sequence=60, worktree="YOK-60"
        )
        project_repo = tmp_path / "repo"
        project_repo.mkdir()

        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout="  trial/YOK-60\n"),
                mock.Mock(returncode=0, stdout=""),  # ancestry
                mock.Mock(returncode=0, stdout=""),  # branch -D
            ]
            assert (
                done_transition._cleanup_trial_branches(project_repo, item_id=600)
                is True
            )

        listing = run_git.call_args_list[0].args[0]
        assert listing[-1] == "trial/YOK-60"
        assert "trial/YOK-600" not in listing
        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert any("branch -D trial/YOK-60" in command for command in commands)
