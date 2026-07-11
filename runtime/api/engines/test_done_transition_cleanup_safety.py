"""Fail-closed done-transition cleanup regressions."""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from yoke_core.engines import done_transition, done_transition_cleanup
from yoke_core.engines._done_transition_test_helpers import dt_db as _shared_dt_db
from runtime.api.test_backlog import _seed_claim


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _git_args(repo, *args):
    return ["git", "-C", str(repo), *args]


@pytest.fixture
def dt_db(tmp_path, monkeypatch):
    yield from _shared_dt_db.__wrapped__(tmp_path, monkeypatch)


class TestCleanupStaleBranches:
    def test_preserves_unregistered_worktree_and_files(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        wt_dir = project_repo / ".worktrees" / TEST_ITEM_REF
        wt_dir.mkdir(parents=True)
        (wt_dir / "leftover.txt").write_text("stale content")

        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # valid branch metadata
                mock.Mock(returncode=0, stdout=""),
                mock.Mock(returncode=0, stdout=""),
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

    def test_preserves_dirty_registered_worktree(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        wt_dir = project_repo / ".worktrees" / TEST_ITEM_REF
        wt_dir.mkdir(parents=True)

        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # valid branch metadata
                mock.Mock(returncode=0, stdout=""),
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

        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # fetch target
                mock.Mock(returncode=0, stdout="abc\n"),  # local ref
                mock.Mock(returncode=0, stdout=""),  # local ancestry
                mock.Mock(returncode=0, stdout=""),  # normal delete
                mock.Mock(returncode=0, stdout=""),  # remote absent
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, "", project_repo
            )

        assert complete is True
        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert any(f"branch -d {TEST_ITEM_REF}" in command for command in commands)
        assert not any("branch -D" in command for command in commands)

    def test_remote_delete_refusal_preserves_metadata(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        project_repo.mkdir()

        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # fetch target
                mock.Mock(returncode=1, stdout=""),  # no local branch
                mock.Mock(
                    returncode=0,
                    stdout=f"abc\trefs/heads/{TEST_ITEM_REF}\n",
                ),
                mock.Mock(returncode=0, stdout=""),  # fetch exact remote
                mock.Mock(returncode=0, stdout=""),  # remote ancestry
                mock.Mock(returncode=0, stdout="abc\n"),  # expected remote sha
                mock.Mock(returncode=1, stdout=""),  # remote delete refused
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, "", project_repo
            )

        assert complete is False
        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert any(
            f"merge-base --is-ancestor origin/{TEST_ITEM_REF} origin/main" in command
            for command in commands
        )
        assert any(
            f"push --force-with-lease=refs/heads/{TEST_ITEM_REF}:abc origin "
            f":refs/heads/{TEST_ITEM_REF}" in command
            for command in commands
        )

    def test_concurrent_remote_update_survives_leased_delete(
        self, tmp_path, monkeypatch
    ):
        origin = tmp_path / "origin.git"
        project_repo = tmp_path / "repo"
        subprocess.run(
            ["git", "init", "--bare", "--initial-branch=main", str(origin)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(project_repo)],
            check=True,
            capture_output=True,
            text=True,
        )
        for key, value in (
            ("user.email", "test@example.com"),
            ("user.name", "Test"),
        ):
            subprocess.run(
                ["git", "-C", str(project_repo), "config", key, value],
                check=True,
            )
        (project_repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(project_repo), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(project_repo), "commit", "-m", "base"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(project_repo), "remote", "add", "origin", str(origin)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(project_repo), "push", "origin", "main"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            _git_args(project_repo, "branch", TEST_ITEM_REF),
            check=True,
        )
        subprocess.run(
            _git_args(project_repo, "push", "origin", TEST_ITEM_REF),
            check=True,
            capture_output=True,
        )

        concurrent_sha = ""

        def run_git(args, capture=False, **_kwargs):
            nonlocal concurrent_sha
            if args[2] == "push" and any(
                value.startswith("--force-with-lease=") for value in args
            ):
                head = subprocess.check_output(
                    _git_args(project_repo, "rev-parse", TEST_ITEM_REF),
                    text=True,
                ).strip()
                tree = subprocess.check_output(
                    _git_args(
                        project_repo,
                        "rev-parse",
                        f"{TEST_ITEM_REF}^{{tree}}",
                    ),
                    text=True,
                ).strip()
                concurrent_sha = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(project_repo),
                        "commit-tree",
                        tree,
                        "-p",
                        head,
                    ],
                    input="concurrent remote work\n",
                    text=True,
                    check=True,
                    capture_output=True,
                ).stdout.strip()
                subprocess.run(
                    _git_args(
                        project_repo,
                        "push",
                        "origin",
                        f"{concurrent_sha}:refs/heads/{TEST_ITEM_REF}",
                    ),
                    check=True,
                    capture_output=True,
                )
            return subprocess.run(
                ["git", *args],
                text=True,
                check=False,
                capture_output=True,
            )

        monkeypatch.setattr(done_transition, "_run_git", run_git)

        assert (
            done_transition_cleanup._delete_remote_if_merged(
                project_repo, TEST_ITEM_REF, "origin/main"
            )
            is False
        )
        advertised = subprocess.check_output(
            _git_args(project_repo, "ls-remote", "origin", TEST_ITEM_REF),
            text=True,
        )
        assert advertised.split()[0] == concurrent_sha

    def test_remote_ref_match_is_field_exact(self, dt_db, tmp_path):
        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        with mock.patch.object(done_transition, "_run_git") as run_git:
            run_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),  # fetch target
                mock.Mock(returncode=1, stdout=""),  # no local branch
                mock.Mock(
                    returncode=0,
                    stdout=f"abc\trefs/heads/{TEST_ITEM_REF}0\n",
                ),
            ]
            complete = done_transition._cleanup_stale_branches(
                TEST_ITEM_ID, "", project_repo
            )

        assert complete is True
        commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
        assert not any("push origin --delete" in command for command in commands)

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
