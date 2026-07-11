"""Local-merge cleanup preserves filesystem-only work."""

from __future__ import annotations

from contextlib import ExitStack
from unittest import mock

from yoke_core.engines import merge_worktree
from yoke_core.engines import merge_worktree_post_local


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _ctx(tmp_path):
    repo = tmp_path / "repo"
    worktree = repo / ".worktrees" / TEST_ITEM_REF
    worktree.mkdir(parents=True)
    return merge_worktree.MergeContext(
        args=merge_worktree.MergeArgs(
            branch=TEST_ITEM_REF, target="main", local_merge=True
        ),
        repo_root=str(repo),
        yoke_repo_root=str(repo),
        worktree_path=str(worktree),
    )


def _patch_post_steps():
    stack = ExitStack()
    stack.enter_context(
        mock.patch.object(merge_worktree_post_local, "_ensure_snapshot_for_project")
    )
    stack.enter_context(
        mock.patch.object(merge_worktree_post_local, "_chdir_out_of_doomed_worktree")
    )
    stack.enter_context(mock.patch.object(merge_worktree_post_local, "_schema_refresh"))
    stack.enter_context(
        mock.patch.object(
            merge_worktree_post_local,
            "_regenerate_views_or_exit5",
            return_value=0,
        )
    )
    stack.enter_context(
        mock.patch.object(merge_worktree_post_local, "_ensure_target_branch")
    )
    return stack


def test_dirty_or_ignored_worktree_is_preserved(tmp_path):
    ctx = _ctx(tmp_path)
    with _patch_post_steps(), mock.patch.object(merge_worktree, "_run_git") as run_git:
        run_git.side_effect = [
            mock.Mock(returncode=0, stdout=""),  # checkout target
            mock.Mock(returncode=0, stdout=""),  # local merge
            mock.Mock(returncode=0, stdout="!! cache/\n"),
        ]
        assert merge_worktree_post_local.do_local_merge(ctx) == 0

    commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
    assert any("--ignored=matching" in command for command in commands)
    assert not any("worktree remove" in command for command in commands)
    assert not any("branch -d" in command for command in commands)


def test_clean_worktree_uses_normal_remove_before_branch_delete(tmp_path):
    ctx = _ctx(tmp_path)
    with _patch_post_steps(), mock.patch.object(merge_worktree, "_run_git") as run_git:
        run_git.side_effect = [
            mock.Mock(returncode=0, stdout=""),  # checkout target
            mock.Mock(returncode=0, stdout=""),  # local merge
            mock.Mock(returncode=0, stdout=""),  # initial clean status
            mock.Mock(returncode=0, stdout=""),  # final clean status
            mock.Mock(returncode=0, stdout=""),  # worktree remove
            mock.Mock(returncode=0, stdout=""),  # branch -d
        ]
        assert merge_worktree_post_local.do_local_merge(ctx) == 0

    commands = [" ".join(call.args[0]) for call in run_git.call_args_list]
    remove_index = next(
        i for i, command in enumerate(commands) if "worktree remove" in command
    )
    branch_index = next(
        i for i, command in enumerate(commands) if "branch -d" in command
    )
    assert remove_index < branch_index
    assert not any(
        "--force" in command or "branch -D" in command for command in commands
    )
