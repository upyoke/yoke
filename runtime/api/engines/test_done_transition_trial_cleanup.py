"""Trial-branch cleanup behavior for completed backlog items."""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.engines import done_transition
from yoke_core.engines._done_transition_test_helpers import (
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
                mock.Mock(returncode=0, stdout=""),  # branch -d
            ]
            assert done_transition._cleanup_trial_branches(project_repo) is True

        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert any("branch -d trial/YOK-99" in command for command in commands)
        assert not any("branch -D" in command for command in commands)

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
