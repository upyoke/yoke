"""Targeted regressions for the checked-out post-merge sync path.

The broader behavioural coverage for ``_sync_local_target`` -- happy
path, dirty-tree stash/restore, timeout handling, noninteractive git
env, the AST regression guard -- lives in ``test_merge_worktree_sync``.
This sibling file is the narrow guardrail for the YOK-1842 fix: when
the target branch is currently checked out in the main repo, the sync
primitive must NOT run ``git pull`` (which can surface
``Cannot fast-forward to multiple branches`` under some tracking
configs) and MUST instead issue an explicit
``git fetch origin {target}`` followed by
``git merge --ff-only origin/{target}``.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.engines import merge_worktree
from yoke_core.engines.merge_worktree import MergeArgs, MergeContext


@pytest.fixture
def sync_ctx(tmp_path, monkeypatch):
    ctx = MergeContext(args=MergeArgs(branch="YOK-9999", target="main"))
    ctx.repo_root = str(tmp_path)
    ctx.yoke_repo_root = str(tmp_path)
    ctx.item_id = "9999"
    ctx.epic_id = None
    monkeypatch.setattr(merge_worktree, "_print", lambda *a, **kw: None)
    return ctx


class TestCheckedOutTargetExplicitSequence:
    """AC-6 / AC-10 / AC-11: pin the explicit fetch + ff-only-merge shape."""

    def test_checked_out_target_uses_explicit_fetch_then_ff_only_merge(
        self, sync_ctx, monkeypatch
    ):
        """The checked-out path must dispatch exactly ``git fetch origin
        {target}`` followed by ``git merge --ff-only origin/{target}`` --
        never ``git pull`` -- so future changes cannot reintroduce the
        multi-branch fast-forward ambiguity that triggered the original
        post-merge cleanup exit-5."""
        sha = "abc1234567890"
        calls: list[list[str]] = []
        env_seen: list[dict] = []
        timeout_seen: list[int | None] = []

        def fake_run(
            cmd,
            cwd=None,
            capture_output=False,
            text=False,
            timeout=None,
            env=None,
        ):
            calls.append(list(cmd))
            env_seen.append(env or {})
            timeout_seen.append(timeout)
            return mock.Mock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_run_git(cmd, cwd=None, capture=False):
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            if cmd[0] == "status":
                result.stdout = ""
            elif cmd[0] == "rev-parse" and len(cmd) > 1:
                if cmd[1] == "--abbrev-ref":
                    result.stdout = "main"  # ON main -- checked-out case
                elif cmd[1] == "main":
                    result.stdout = sha
                elif cmd[1] == "origin/main":
                    result.stdout = sha
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is True

        for cmd in calls:
            assert "pull" not in cmd, (
                f"checked-out sync path must not use git pull; got {cmd!r}"
            )

        assert len(calls) == 2, (
            "expected exactly two subprocess.run calls (fetch + merge), got "
            f"{calls!r}"
        )
        assert calls[0] == ["git", "fetch", "origin", "main"], calls[0]
        assert calls[1] == ["git", "merge", "--ff-only", "origin/main"], calls[1]

        # Both subprocess calls reuse the same configured timeout.
        assert len(set(timeout_seen)) == 1, (
            "fetch + merge must reuse the same post_merge_rebase_timeout; "
            f"saw {timeout_seen!r}"
        )
        assert timeout_seen[0] is not None and timeout_seen[0] > 0

        # Both subprocess calls run under the noninteractive git env so the
        # fetch / merge cannot stall waiting on a credential prompt.
        for env in env_seen:
            assert env.get("GIT_TERMINAL_PROMPT") == "0"

    def test_checked_out_fetch_failure_skips_merge_and_returns_false(
        self, sync_ctx, monkeypatch
    ):
        """When the explicit fetch step fails on the checked-out target,
        the merge step must not run and the sync returns False so the
        caller can surface the exit-5 LocalTargetSyncFailed class."""
        calls: list[list[str]] = []

        def fake_run(
            cmd,
            cwd=None,
            capture_output=False,
            text=False,
            timeout=None,
            env=None,
        ):
            calls.append(list(cmd))
            return mock.Mock(returncode=1, stdout="", stderr="fetch denied")

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_run_git(cmd, cwd=None, capture=False):
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            if cmd[0] == "rev-parse" and len(cmd) > 1 and cmd[1] == "--abbrev-ref":
                result.stdout = "main"  # checked-out
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is False
        assert calls == [["git", "fetch", "origin", "main"]], calls

    def test_not_checked_out_target_keeps_direct_ref_update(
        self, sync_ctx, monkeypatch
    ):
        """The not-checked-out branch path is unchanged by YOK-1842 -- it
        still uses a single ``git fetch origin {target}:{target}`` to
        update the local ref directly. Pin the shape so future refactors
        of the checked-out path cannot collapse both branches together
        and lose the worktree-friendly behaviour."""
        sha = "abc1234567890"
        calls: list[list[str]] = []

        def fake_run(
            cmd,
            cwd=None,
            capture_output=False,
            text=False,
            timeout=None,
            env=None,
        ):
            calls.append(list(cmd))
            return mock.Mock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_run_git(cmd, cwd=None, capture=False):
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            if cmd[0] == "status":
                result.stdout = ""
            elif cmd[0] == "rev-parse" and len(cmd) > 1:
                if cmd[1] == "--abbrev-ref":
                    result.stdout = "YOK-9999"  # NOT on main
                elif cmd[1] == "main":
                    result.stdout = sha
                elif cmd[1] == "origin/main":
                    result.stdout = sha
            return result

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

        assert merge_worktree._sync_local_target(sync_ctx) is True
        assert calls == [["git", "fetch", "origin", "main:main"]], calls
