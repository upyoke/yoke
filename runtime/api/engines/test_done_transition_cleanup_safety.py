"""Fail-closed done-transition cleanup regressions."""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.engines import done_transition, done_transition_cleanup
from yoke_core.engines._done_transition_test_helpers import dt_db as _shared_dt_db
from yoke_core.engines.remote_branch_cleanup import RemoteBranchDeleteResult
from runtime.api.test_backlog import _seed_claim


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"
NON_PREFIX_BRANCH = "codex/remote-first-lane"


def _git_args(repo, *args):
    return ["git", "-C", str(repo), *args]


@pytest.fixture
def dt_db(tmp_path, monkeypatch):
    yield from _shared_dt_db.__wrapped__(tmp_path, monkeypatch)


def _remote_absent(**_kwargs):
    return RemoteBranchDeleteResult("absent", "remote branch is absent")


def _remote_preserved(**_kwargs):
    return RemoteBranchDeleteResult(
        "preserved", "leased remote delete was refused"
    )


class TestCleanupStaleBranches:
    def test_preserves_unregistered_worktree_and_files(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        wt_dir = project_repo / ".worktrees" / TEST_ITEM_REF
        wt_dir.mkdir(parents=True)
        (wt_dir / "leftover.txt").write_text("stale content")

        with mock.patch.object(done_transition, "_run_git") as run_git, mock.patch(
            "yoke_core.engines.done_transition_cleanup.delete_remote_branch_if_merged",
            side_effect=_remote_absent,
        ):
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # valid branch metadata
                mock.Mock(returncode=0, stdout=""),  # fetch target
                mock.Mock(returncode=0, stdout=""),  # worktree list (unregistered)
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, TEST_ITEM_REF, project_repo
            )

        assert complete is False
        assert (wt_dir / "leftover.txt").read_text() == "stale content"
        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert not any(
            "--force" in command or "branch -D" in command for command in commands
        )
        assert not any("worktree remove" in command for command in commands)

    def test_preserves_dirty_registered_worktree(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        wt_dir = project_repo / ".worktrees" / TEST_ITEM_REF
        wt_dir.mkdir(parents=True)

        with mock.patch.object(done_transition, "_run_git") as run_git, mock.patch(
            "yoke_core.engines.done_transition_cleanup.delete_remote_branch_if_merged",
            side_effect=_remote_absent,
        ):
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # valid branch metadata
                mock.Mock(returncode=0, stdout=""),  # fetch target
                mock.Mock(
                    returncode=0,
                    stdout=(
                        f"worktree {wt_dir}\nbranch refs/heads/{TEST_ITEM_REF}\n\n"
                    ),
                ),
                mock.Mock(returncode=0, stdout="!! local-cache/\n"),
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, TEST_ITEM_REF, project_repo
            )

        assert complete is False
        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert not any("worktree remove" in command for command in commands)

    def test_deletes_only_proven_local_branch(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        remote_calls: list[str] = []

        def capture_remote(*, branch, target_branch, **_kwargs):
            remote_calls.append(branch)
            return _remote_absent()

        with mock.patch.object(done_transition, "_run_git") as run_git, mock.patch(
            "yoke_core.engines.done_transition_cleanup.delete_remote_branch_if_merged",
            side_effect=capture_remote,
        ):
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # fetch target
                mock.Mock(returncode=0, stdout="abc\n"),  # local ref
                mock.Mock(returncode=0, stdout=""),  # local ancestry
                mock.Mock(returncode=0, stdout=""),  # normal delete
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, "", project_repo
            )

        assert complete is True
        assert remote_calls == [TEST_ITEM_REF]
        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert any(f"branch -d {TEST_ITEM_REF}" in command for command in commands)
        assert not any("branch -D" in command for command in commands)

    def test_remote_delete_runs_before_local_discard(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        wt_dir = project_repo / ".worktrees" / TEST_ITEM_REF
        wt_dir.mkdir(parents=True)
        timeline: list[str] = []

        def capture_remote(**_kwargs):
            timeline.append("remote-delete")
            return RemoteBranchDeleteResult("deleted", "remote branch was deleted")

        def run_git(args, capture=False, **_kwargs):
            joined = " ".join(args)
            if "worktree remove" in joined:
                timeline.append("worktree-remove")
            elif "branch -d" in joined:
                timeline.append("local-delete")
            if args[2:] == ["check-ref-format", "--branch", TEST_ITEM_REF]:
                return mock.Mock(returncode=0, stdout="")
            if args[2:] == ["fetch", "origin", "main"]:
                return mock.Mock(returncode=0, stdout="")
            if args[2:4] == ["worktree", "list"]:
                return mock.Mock(
                    returncode=0,
                    stdout=(
                        f"worktree {wt_dir}\nbranch refs/heads/{TEST_ITEM_REF}\n\n"
                    ),
                )
            if "status" in args:
                return mock.Mock(returncode=0, stdout="")
            if "merge-base" in args:
                return mock.Mock(returncode=0, stdout="")
            if "worktree" in args and "remove" in args:
                return mock.Mock(returncode=0, stdout="")
            if "branch" in args and "-d" in args:
                return mock.Mock(returncode=0, stdout="")
            if "rev-parse" in args:
                return mock.Mock(returncode=0, stdout="abc\n")
            return mock.Mock(returncode=0, stdout="")

        with mock.patch.object(done_transition, "_run_git", side_effect=run_git), mock.patch(
            "yoke_core.engines.done_transition_cleanup.delete_remote_branch_if_merged",
            side_effect=capture_remote,
        ), mock.patch(
            "yoke_core.engines.merge_worktree_cleanliness.clean_after_disposable_cache_removal",
            return_value=True,
        ):
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, TEST_ITEM_REF, project_repo
            )

        assert complete is True
        assert timeline.index("remote-delete") < timeline.index("worktree-remove")
        assert timeline.index("worktree-remove") < timeline.index("local-delete")

    def test_remote_delete_refusal_preserves_local_lane(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        wt_dir = project_repo / ".worktrees" / TEST_ITEM_REF
        wt_dir.mkdir(parents=True)
        (wt_dir / "keep.txt").write_text("retry lane\n")

        with mock.patch.object(done_transition, "_run_git") as run_git, mock.patch(
            "yoke_core.engines.done_transition_cleanup.delete_remote_branch_if_merged",
            side_effect=_remote_preserved,
        ):
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # valid branch
                mock.Mock(returncode=0, stdout=""),  # fetch target
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, TEST_ITEM_REF, project_repo
            )

        assert complete is False
        assert (wt_dir / "keep.txt").read_text() == "retry lane\n"
        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert not any("worktree remove" in command for command in commands)
        assert not any("branch -d" in command for command in commands)

    def test_uses_shared_helper_only(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        assert not hasattr(done_transition_cleanup, "_delete_remote_if_merged")

        with mock.patch.object(done_transition, "_run_git") as run_git, mock.patch(
            "yoke_core.engines.done_transition_cleanup.delete_remote_branch_if_merged",
            side_effect=_remote_absent,
        ) as shared:
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # fetch target
                mock.Mock(returncode=1, stdout=""),  # no local branch
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, "", project_repo
            )

        assert complete is True
        shared.assert_called_once()
        assert shared.call_args.kwargs["branch"] == TEST_ITEM_REF
        assert shared.call_args.kwargs["target_branch"] == "main"

    def test_non_prefix_lane_name_uses_exact_branch(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        seen: list[str] = []

        def capture_remote(*, branch, **_kwargs):
            seen.append(branch)
            return _remote_absent()

        with mock.patch.object(done_transition, "_run_git") as run_git, mock.patch(
            "yoke_core.engines.done_transition_cleanup.delete_remote_branch_if_merged",
            side_effect=capture_remote,
        ):
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # valid branch
                mock.Mock(returncode=0, stdout=""),  # fetch target
                mock.Mock(returncode=1, stdout=""),  # no local branch
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, NON_PREFIX_BRANCH, project_repo
            )

        assert complete is True
        assert seen == [NON_PREFIX_BRANCH]

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

        with mock.patch.object(done_transition, "_run_git") as run_git:
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, TEST_ITEM_REF, project_repo
            )

        assert complete is False
        run_git.assert_not_called()


class TestDoneRunnerHonorsCleanupFailure:
    def test_incomplete_cleanup_blocks_done(self, dt_db):
        db_path, _ = dt_db
        from yoke_core.engines._done_transition_test_helpers import _insert_item

        repo_root = db_path.parent
        _insert_item(db_path, TEST_ITEM_ID, status="reviewed-implementation")

        with (
            mock.patch.object(
                done_transition, "_resolve_repo_root", return_value=repo_root
            ),
            mock.patch.object(
                done_transition,
                "_resolve_project_context",
                return_value=(repo_root, ""),
            ),
            mock.patch.object(done_transition, "_get_base_branch", return_value="main"),
            mock.patch.object(done_transition, "_check_merge_guard", return_value=True),
            mock.patch.object(
                done_transition, "_verify_recovery_evidence", return_value=True
            ),
            mock.patch.object(
                done_transition, "_cleanup_stale_branches", return_value=False
            ) as cleanup,
            mock.patch.object(
                done_transition, "_update_status_to_done"
            ) as update_done,
            mock.patch.object(done_transition, "_finalize_done_local_side_effects"),
            mock.patch.object(done_transition, "_verify_cwd_after_merge"),
            mock.patch.object(done_transition, "_schema_gate"),
            mock.patch.object(
                done_transition, "_check_deployment_flow_guard", return_value=None
            ),
            mock.patch.object(done_transition, "_populate_merged_at"),
        ):
            rc = done_transition.run(TEST_ITEM_ID)

        assert rc == 1
        cleanup.assert_called_once()
        update_done.assert_not_called()
