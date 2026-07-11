"""Safety regressions for detached trial merges."""

from __future__ import annotations

from unittest import mock

from yoke_core.engines import merge_worktree


def _ctx(tmp_path):
    return merge_worktree.MergeContext(
        args=merge_worktree.MergeArgs(branch="YOK-42", target="main"),
        repo_root=str(tmp_path),
        worktree_path=str(tmp_path),
    )


def test_non_conflict_merge_failure_restores_and_fails(tmp_path):
    ctx = _ctx(tmp_path)
    with mock.patch.object(merge_worktree, "_run_git") as run_git:
        run_git.side_effect = [
            mock.Mock(returncode=0, stdout="", stderr=""),  # detach
            mock.Mock(returncode=2, stdout="", stderr="object missing"),
            mock.Mock(returncode=0, stdout="", stderr=""),  # no conflicts
            mock.Mock(returncode=1, stdout="", stderr=""),  # no merge to abort
            mock.Mock(returncode=0, stdout="", stderr=""),  # restore branch
        ]
        result = merge_worktree.trial_merge(ctx)

    assert result == (1, [])
    commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
    assert "checkout YOK-42" in commands
    assert not any("branch -D" in command for command in commands)


def test_detach_refusal_stops_before_merge(tmp_path):
    ctx = _ctx(tmp_path)
    with mock.patch.object(merge_worktree, "_run_git") as run_git:
        run_git.return_value = mock.Mock(returncode=1, stdout="", stderr="busy")
        result = merge_worktree.trial_merge(ctx)

    assert result == (1, [])
    assert run_git.call_count == 1
    assert run_git.call_args.args[0] == ["checkout", "--detach", "YOK-42"]


def test_failed_trial_reports_restore_failure_as_error(tmp_path):
    ctx = _ctx(tmp_path)
    with mock.patch.object(merge_worktree, "_run_git") as run_git:
        run_git.side_effect = [
            mock.Mock(returncode=0, stdout="", stderr=""),  # detach
            mock.Mock(returncode=2, stdout="", stderr="hook failed"),
            mock.Mock(returncode=0, stdout="", stderr=""),  # no conflicts
            mock.Mock(returncode=0, stdout="", stderr=""),  # abort
            mock.Mock(returncode=1, stdout="", stderr="busy"),  # restore
        ]
        assert merge_worktree.trial_merge(ctx) == (1, [])

    assert run_git.call_args_list[-1].args[0] == ["checkout", "YOK-42"]


def test_successful_trial_aborts_uncommitted_merge_before_restore(tmp_path):
    ctx = _ctx(tmp_path)
    with mock.patch.object(merge_worktree, "_run_git") as run_git:
        run_git.side_effect = [
            mock.Mock(returncode=0, stdout="", stderr=""),  # detach
            mock.Mock(returncode=0, stdout="", stderr=""),  # merge staged
            mock.Mock(returncode=0, stdout="abc\n", stderr=""),  # MERGE_HEAD
            mock.Mock(returncode=0, stdout="", stderr=""),  # abort
            mock.Mock(returncode=0, stdout="", stderr=""),  # restore
        ]
        assert merge_worktree.trial_merge(ctx) is None

    commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
    assert "merge --no-commit --no-ff origin/main" in commands
    assert commands.index("merge --abort") < commands.index("checkout YOK-42")


def test_already_current_trial_restores_without_abort(tmp_path):
    ctx = _ctx(tmp_path)
    with mock.patch.object(merge_worktree, "_run_git") as run_git:
        run_git.side_effect = [
            mock.Mock(returncode=0, stdout="", stderr=""),  # detach
            mock.Mock(returncode=0, stdout="Already up-to-date.\n", stderr=""),
            mock.Mock(returncode=1, stdout="", stderr=""),  # no MERGE_HEAD
            mock.Mock(returncode=0, stdout="", stderr=""),  # restore
        ]
        assert merge_worktree.trial_merge(ctx) is None

    commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
    assert "merge --abort" not in commands
    assert commands[-1] == "checkout YOK-42"
