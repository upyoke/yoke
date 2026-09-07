"""Focused post-merge cleanup regressions for merge_worktree."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from yoke_core.engines import merge_worktree
from yoke_core.engines import merge_worktree_cleanup
from yoke_core.engines import merge_worktree_post_helpers
from yoke_core.engines.merge_worktree import MergeArgs, MergeContext
from yoke_core.engines.remote_branch_cleanup import RemoteBranchDeleteResult


def _cleanup_ctx(tmp_path):
    ctx = MergeContext(args=MergeArgs(branch="YOK-9999", target="main"))
    ctx.repo_root = str(tmp_path)
    ctx.yoke_repo_root = str(tmp_path)
    ctx.item_id = "9999"
    ctx.epic_id = None
    return ctx


class TestPostMergeCleanupLocalSyncFailure:
    """Post-merge local sync failures must stay in the exit-5 class."""

    def test_sync_failure_returns_exit_5_with_precise_event(
        self, tmp_path, monkeypatch
    ):
        ctx = _cleanup_ctx(tmp_path)
        emitted = []
        printed = []

        monkeypatch.setattr(merge_worktree, "_sync_local_target", lambda _ctx: False)
        monkeypatch.setattr(merge_worktree, "_schema_refresh", lambda _ctx: None)
        monkeypatch.setattr(merge_worktree, "_ensure_target_branch", lambda _ctx: None)
        monkeypatch.setattr(
            merge_worktree,
            "_emit_merge_event",
            lambda name, **kw: emitted.append((name, kw)),
        )
        monkeypatch.setattr(
            merge_worktree,
            "_print",
            lambda *args, **kwargs: printed.append((" ".join(map(str, args)), kwargs)),
        )
        monkeypatch.setattr(
            merge_worktree,
            "_run_git",
            lambda cmd, cwd=None, capture=False: mock.Mock(
                returncode=0,
                stdout="",
                stderr="",
            ),
        )

        exit_code = merge_worktree._post_merge_cleanup(
            ctx, no_changes=False, pr_num="3395"
        )

        assert exit_code == 5

        failures = [kw for name, kw in emitted if name == "MergeEngineFailed"]
        assert len(failures) == 1
        detail = failures[0]["context"]
        assert detail["phase"] == "post_merge_cleanup"
        assert detail["merge_committed"] is True
        assert detail["exit_code"] == 5
        assert detail["error_type"] == "LocalTargetSyncFailed"
        assert detail["branch"] == "YOK-9999"
        assert detail["target"] == "main"

        printed_lines = [line for line, _kwargs in printed if line]
        assert any("do NOT roll the item back" in line for line in printed_lines)
        assert any(
            f"YOKE_REPO_ROOT={ctx.yoke_repo_root}" in line for line in printed_lines
        )

        # The recovery text must not point operators at the
        # ambiguous ``git pull --ff-only`` shape this work item retires; it
        # must teach the explicit fetch + ff-only-merge sequence the code
        # itself uses.
        recovery_lines = [line for line in printed_lines if "Recovery:" in line]
        assert recovery_lines, (
            f"expected a Recovery: line in stderr; printed lines were {printed_lines!r}"
        )
        recovery_text = " ".join(recovery_lines)
        assert "git pull" not in recovery_text, (
            "post-merge cleanup recovery text must not recommend git pull; "
            f"got: {recovery_text!r}"
        )
        assert "git fetch origin main" in recovery_text
        assert "git merge --ff-only origin/main" in recovery_text


class TestPostMergeRemoteCleanupSafety:
    def test_remote_cleanup_refusal_preserves_local_retry_lane(
        self, tmp_path, monkeypatch
    ):
        ctx = _cleanup_ctx(tmp_path)
        worktree = tmp_path / ".worktrees" / "YOK-9999"
        worktree.mkdir(parents=True)
        ctx.worktree_path = str(worktree)
        commands: list[list[str]] = []

        monkeypatch.setattr(merge_worktree, "_sync_local_target", lambda _ctx: True)
        monkeypatch.setattr(merge_worktree, "_schema_refresh", lambda _ctx: None)
        monkeypatch.setattr(merge_worktree, "_ensure_target_branch", lambda _ctx: None)
        monkeypatch.setattr(
            merge_worktree, "_emit_merge_event", lambda *args, **kwargs: None
        )
        monkeypatch.setattr(merge_worktree, "_print", lambda *args, **kwargs: None)

        def run_git(command, cwd=None, capture=False):
            commands.append(command)
            return mock.Mock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(merge_worktree, "_run_git", run_git)
        monkeypatch.setattr(
            merge_worktree_cleanup,
            "delete_remote_branch_if_merged",
            lambda **kwargs: RemoteBranchDeleteResult(
                "preserved",
                "leased remote delete was refused",
            ),
        )

        exit_code = merge_worktree._post_merge_cleanup(
            ctx,
            no_changes=True,
        )

        assert exit_code == 0
        assert worktree.is_dir()
        assert not any(command[:2] == ["worktree", "remove"] for command in commands)
        assert not any(command[:2] == ["branch", "-d"] for command in commands)

    def test_local_branch_delete_waits_for_target_sync(self, tmp_path, monkeypatch):
        ctx = _cleanup_ctx(tmp_path)
        worktree = tmp_path / ".worktrees" / "YOK-9999"
        worktree.mkdir(parents=True)
        ctx.worktree_path = str(worktree)
        timeline: list[str] = []
        cleaned_trust: list[Path] = []

        def run_git(command, cwd=None, capture=False):
            del cwd, capture
            timeline.append(" ".join(command))
            return mock.Mock(returncode=0, stdout="", stderr="")

        def sync_target(_ctx):
            timeline.append("sync-target")
            return True

        monkeypatch.setattr(merge_worktree, "_run_git", run_git)
        monkeypatch.setattr(merge_worktree, "_sync_local_target", sync_target)
        monkeypatch.setattr(merge_worktree, "_schema_refresh", lambda _ctx: None)
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
        monkeypatch.setattr(
            merge_worktree_cleanup,
            "worktree_cleanup_warning",
            lambda path: cleaned_trust.append(Path(path)) or "",
        )
        from yoke_core.engines import merge_worktree_cleanliness

        monkeypatch.setattr(
            merge_worktree_cleanliness,
            "clean_after_disposable_cache_removal",
            lambda *args: True,
        )

        assert merge_worktree._post_merge_cleanup(ctx, no_changes=True) == 0
        assert (
            timeline.index("worktree remove " + str(worktree))
            < timeline.index("sync-target")
            < timeline.index("branch -d YOK-9999")
        )
        assert cleaned_trust == [worktree]


class TestChdirOutOfDoomedWorktree:
    """``_chdir_out_of_doomed_worktree`` must escape a doomed worktree cwd.

    When ``merge_worktree`` is invoked with cwd inside the linked worktree
    it is about to remove, later calls to ``os.getcwd()`` (e.g. in the DB
    path resolver) raise ``FileNotFoundError`` once the dir is gone. The
    helper pre-empts that by chdir'ing to ``ctx.repo_root`` when — and only
    when — the current cwd is under the doomed worktree.
    """

    def test_chdir_when_cwd_inside_worktree(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "main"
        repo_root.mkdir()
        worktree = tmp_path / "main" / ".worktrees" / "YOK-1"
        worktree.mkdir(parents=True)

        ctx = MergeContext(args=MergeArgs(branch="YOK-1", target="main"))
        ctx.repo_root = str(repo_root)
        ctx.worktree_path = str(worktree)

        monkeypatch.chdir(worktree)
        merge_worktree_post_helpers._chdir_out_of_doomed_worktree(ctx)
        assert os.path.realpath(os.getcwd()) == os.path.realpath(str(repo_root))

    def test_noop_when_cwd_outside_worktree(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "main"
        repo_root.mkdir()
        worktree = tmp_path / "main" / ".worktrees" / "YOK-1"
        worktree.mkdir(parents=True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        ctx = MergeContext(args=MergeArgs(branch="YOK-1", target="main"))
        ctx.repo_root = str(repo_root)
        ctx.worktree_path = str(worktree)

        monkeypatch.chdir(elsewhere)
        merge_worktree_post_helpers._chdir_out_of_doomed_worktree(ctx)
        assert os.path.realpath(os.getcwd()) == os.path.realpath(str(elsewhere))

    def test_noop_when_worktree_path_empty(self, tmp_path, monkeypatch):
        ctx = MergeContext(args=MergeArgs(branch="YOK-1", target="main"))
        ctx.repo_root = str(tmp_path)
        ctx.worktree_path = ""

        monkeypatch.chdir(tmp_path)
        # Must not raise and must not chdir anywhere.
        merge_worktree_post_helpers._chdir_out_of_doomed_worktree(ctx)
        assert os.path.realpath(os.getcwd()) == os.path.realpath(str(tmp_path))
