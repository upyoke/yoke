"""The merge cleanup must not delete the code its close-out still imports.

A process that loaded its packages out of the lane resolves the imports the
close-out still owes — GitHub sync, board rebuild, the terminal transition —
against a directory the removal is about to delete, so a merge that landed
exits non-zero on ``ImportError`` and leaves the item mid-close-out. The
reseat itself is covered in ``runtime/api/domain/test_worktree_import_reseat``;
what matters here is that the cleanup runs it while the lane still exists.
"""

from __future__ import annotations

from unittest import mock

from yoke_core.engines import merge_worktree
from yoke_core.engines import merge_worktree_cleanup
from yoke_core.engines.merge_worktree import MergeArgs, MergeContext
from yoke_core.engines.remote_branch_cleanup import RemoteBranchDeleteResult


def _cleanup_ctx(tmp_path):
    ctx = MergeContext(args=MergeArgs(branch="YOK-9999", target="main"))
    ctx.repo_root = str(tmp_path)
    ctx.yoke_repo_root = str(tmp_path)
    ctx.item_id = "9999"
    ctx.epic_id = None
    return ctx


class TestImportsSurviveLaneRemoval:
    """The close-out still owes lazy imports when the lane disappears.

    A process that loaded its packages out of the lane resolves those imports
    against a directory the removal is about to delete, so a merge that landed
    exits non-zero on ``ImportError`` and leaves the item mid-close-out.
    """

    def test_packages_are_repointed_before_the_worktree_is_removed(
        self, tmp_path, monkeypatch,
    ):
        ctx = _cleanup_ctx(tmp_path)
        worktree = tmp_path / ".worktrees" / "YOK-9999"
        worktree.mkdir(parents=True)
        ctx.worktree_path = str(worktree)
        timeline: list[str] = []

        def run_git(command, cwd=None, capture=False):
            del cwd, capture
            timeline.append(" ".join(command))
            return mock.Mock(returncode=0, stdout="", stderr="")

        def reseat(*, doomed_root, surviving_root):
            timeline.append(f"reseat {doomed_root} -> {surviving_root}")
            return []

        monkeypatch.setattr(merge_worktree, "_run_git", run_git)
        monkeypatch.setattr(merge_worktree_cleanup, "reseat_loaded_packages", reseat)
        monkeypatch.setattr(merge_worktree, "_sync_local_target", lambda _ctx: True)
        monkeypatch.setattr(merge_worktree, "_schema_refresh", lambda _ctx: None)
        monkeypatch.setattr(
            merge_worktree, "_regenerate_views_advisory", lambda _ctx: None
        )
        monkeypatch.setattr(merge_worktree, "_ensure_target_branch", lambda _ctx: None)
        monkeypatch.setattr(
            merge_worktree, "_emit_merge_event", lambda *args, **kwargs: None
        )
        monkeypatch.setattr(merge_worktree, "_print", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            merge_worktree_cleanup,
            "delete_remote_branch_if_merged",
            lambda **kwargs: RemoteBranchDeleteResult("deleted", ""),
        )
        from yoke_core.engines import merge_worktree_cleanliness

        monkeypatch.setattr(
            merge_worktree_cleanliness,
            "clean_after_disposable_cache_removal",
            lambda *args: True,
        )
        monkeypatch.setattr(
            merge_worktree_cleanup, "_release_lane_row", lambda _ctx: None
        )

        assert merge_worktree._post_merge_cleanup(ctx, no_changes=True) == 0

        assert f"reseat {worktree} -> {tmp_path}" in timeline
        assert timeline.index(f"reseat {worktree} -> {tmp_path}") < timeline.index(
            "worktree remove " + str(worktree)
        )
