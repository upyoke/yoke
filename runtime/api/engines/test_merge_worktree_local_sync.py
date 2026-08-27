"""Targeted regressions for the checked-out post-merge sync path.

The broader behavioural coverage for ``_sync_local_target`` -- happy
path, dirty-tree stash/restore, timeout handling, the AST regression
guard -- lives in ``test_merge_worktree_sync``. This sibling file is the
narrow guardrail: when the target branch is currently checked out in the
main repo, the sync primitive must NOT run ``git pull`` (which can surface
``Cannot fast-forward to multiple branches`` under some tracking
configs) and MUST instead issue an explicit
``git fetch origin {target}`` followed by
``git merge --ff-only origin/{target}``.

Every command the sync issues -- the local reads and the fetch alike --
goes through ``_run_git``, so that one runner is where the shape is
observed. The environment those commands run under is the runner's own
contract, covered in ``test_merge_worktree`` and the credentialed-git
tests rather than restated here.
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


def _recorder(monkeypatch, *, current_branch, sha="abc1234567890", rc_for=None):
    """Record every ``_run_git`` command and answer the reads the sync makes."""
    calls: list[list[str]] = []
    timeouts: list[int | None] = []

    def fake_run_git(cmd, cwd=None, capture=False, timeout=None):
        calls.append(list(cmd))
        timeouts.append(timeout)
        result = mock.Mock()
        result.returncode = (rc_for or {}).get(cmd[0], 0)
        result.stdout = ""
        result.stderr = "fetch denied" if result.returncode else ""
        if cmd[0] == "rev-parse" and len(cmd) > 1:
            if cmd[1] == "--abbrev-ref":
                result.stdout = current_branch
            elif cmd[1] in ("main", "origin/main"):
                result.stdout = sha
        return result

    monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)
    return calls, timeouts


def _network_calls(calls: list[list[str]]) -> list[list[str]]:
    return [cmd for cmd in calls if cmd[0] in ("fetch", "merge", "pull")]


class TestCheckedOutTargetExplicitSequence:
    """Pin the explicit fetch + ff-only-merge shape."""

    def test_checked_out_target_uses_explicit_fetch_then_ff_only_merge(
        self, sync_ctx, monkeypatch
    ):
        """The checked-out path must dispatch exactly ``git fetch origin
        {target}`` followed by ``git merge --ff-only origin/{target}`` --
        never ``git pull`` -- so future changes cannot reintroduce the
        multi-branch fast-forward ambiguity that triggered the original
        post-merge cleanup exit-5."""
        calls, timeouts = _recorder(monkeypatch, current_branch="main")

        assert merge_worktree._sync_local_target(sync_ctx) is True

        for cmd in calls:
            assert "pull" not in cmd, (
                f"checked-out sync path must not use git pull; got {cmd!r}"
            )
        assert _network_calls(calls) == [
            ["fetch", "origin", "main"],
            ["merge", "--ff-only", "origin/main"],
        ], calls

        # Both bounded steps reuse the same configured timeout.
        bounded = [
            timeout
            for cmd, timeout in zip(calls, timeouts)
            if cmd[0] in ("fetch", "merge")
        ]
        assert len(set(bounded)) == 1, (
            "fetch + merge must reuse the same post_merge_rebase_timeout; "
            f"saw {bounded!r}"
        )
        assert bounded[0] is not None and bounded[0] > 0

    def test_checked_out_fetch_failure_skips_merge_and_returns_false(
        self, sync_ctx, monkeypatch
    ):
        """When the explicit fetch step fails on the checked-out target,
        the merge step must not run and the sync returns False so the
        caller can surface the exit-5 LocalTargetSyncFailed class."""
        calls, _ = _recorder(
            monkeypatch, current_branch="main", rc_for={"fetch": 1},
        )

        assert merge_worktree._sync_local_target(sync_ctx) is False
        assert _network_calls(calls) == [["fetch", "origin", "main"]], calls

    def test_not_checked_out_target_keeps_direct_ref_update(
        self, sync_ctx, monkeypatch
    ):
        """The not-checked-out branch path still uses a single
        ``git fetch origin {target}:{target}`` to update the local ref
        directly. Pin the shape so future refactors of the checked-out
        path cannot collapse both branches together and lose the
        worktree-friendly behaviour."""
        calls, _ = _recorder(monkeypatch, current_branch="YOK-9999")

        assert merge_worktree._sync_local_target(sync_ctx) is True
        assert _network_calls(calls) == [["fetch", "origin", "main:main"]], calls
