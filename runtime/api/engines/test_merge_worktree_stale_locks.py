"""Tests for the pre-acquire merge-lock retry path in merge_worktree_runner.

Covers two outcomes: retry success (a transient block message clears on a
later check call) and retry exhaustion (block message persists across the
full retry budget, runner returns the recoverable exit code). Both tests
assert no real ``time.sleep`` delay is incurred so the suite stays fast.

Sibling to ``test_merge_worktree_locks.py``; kept separate so the existing
334-line lock-test file does not grow further.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import pytest

from yoke_core.engines import merge_worktree
from yoke_core.engines import merge_worktree_runner
from yoke_core.engines.merge_worktree import MergeArgs, MergeContext
from yoke_core.engines.merge_worktree_runner import (
    MERGE_LOCK_RETRY_DELAYS,
    RECOVERABLE_MERGE_LOCK_EXIT_CODE,
    _pre_acquire_check_with_retry,
)

from yoke_core.engines._merge_worktree_test_helpers import mw_db


class TestPreAcquireCheckRetryUnit:
    """Direct unit coverage of the retry helper."""

    def test_returns_none_immediately_when_first_check_clear(self):
        sleeps: list[float] = []
        result = _pre_acquire_check_with_retry(
            lambda: None,
            sleep_fn=sleeps.append,
        )
        assert result is None
        assert sleeps == []

    def test_returns_none_when_retry_clears_block(self):
        responses = iter(["Merge lock held by session 12345-1 on branch 'X'", None])
        sleeps: list[float] = []
        result = _pre_acquire_check_with_retry(
            lambda: next(responses),
            sleep_fn=sleeps.append,
        )
        assert result is None
        # One sleep before the retry that cleared the block.
        assert sleeps == [MERGE_LOCK_RETRY_DELAYS[0]]

    def test_returns_final_block_when_budget_exhausted(self):
        responses: list[Optional[str]] = [
            "Merge lock held by session 999-1 on branch 'X'",
            "Merge lock held by session 999-2 on branch 'X'",
            "Merge lock held by session 999-3 on branch 'X'",
            "Merge lock held by session 999-4 on branch 'X'",
        ]
        idx = {"i": 0}

        def fake_check():
            value = responses[idx["i"]]
            idx["i"] += 1
            return value

        sleeps: list[float] = []
        result = _pre_acquire_check_with_retry(
            fake_check,
            sleep_fn=sleeps.append,
        )
        assert result == "Merge lock held by session 999-4 on branch 'X'"
        assert sleeps == list(MERGE_LOCK_RETRY_DELAYS)


@pytest.fixture
def stale_lock_repo(tmp_path, mw_db):
    """Create a minimal git repo wired into the mw_db fixture for runner tests.

    The runner's ``run`` entrypoint exits early on validation/context issues if
    the repo doesn't exist; this fixture provisions just enough so the lock
    check is the first failure surface exercised by the test.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "T"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@e"], check=True, capture_output=True
    )
    (repo / "README.md").write_text("init\n")
    subprocess.run(
        ["git", "-C", str(repo), "add", "README.md"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "branch", "STALE-LOCK-BRANCH"],
        check=True,
        capture_output=True,
    )
    return {"repo": repo, "mw_db": mw_db}


class TestRunnerStaleLockRetry:
    """End-to-end runner coverage exercising the lock-check block."""

    def _build_context(self, repo: Path) -> MergeContext:
        ctx = MergeContext(args=MergeArgs(branch="STALE-LOCK-BRANCH"))
        ctx.repo_root = str(repo)
        ctx.worktree_path = str(repo)
        ctx.yoke_repo_root = str(repo)
        ctx.item_id = None
        ctx.epic_id = None
        return ctx

    def _install_pre_lock_stubs(self, monkeypatch, ctx: MergeContext, messages: list[str]):
        """Make every pre-lock step a no-op so the lock block is reached."""
        monkeypatch.setattr(
            merge_worktree,
            "_print",
            lambda msg="", err=False: messages.append(msg),
        )
        monkeypatch.setattr(merge_worktree, "validate_args", lambda args: None)
        monkeypatch.setattr(merge_worktree, "resolve_context", lambda args: ctx)
        monkeypatch.setattr(
            merge_worktree,
            "_already_merged_message",
            lambda branch, target, root: "",
        )
        monkeypatch.setattr(
            merge_worktree_runner,
            "validate_pat_for_merge",
            lambda _ctx: (True, None),
        )

        class FakeRun:
            def __init__(self, returncode: int = 1, stdout: str = "", stderr: str = ""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def fake_run_git(args, cwd, capture=False, **_kw):
            # rev-parse --verify the branch -> success.
            if args[:2] == ["rev-parse", "--verify"]:
                return FakeRun(returncode=0, stdout="abcd\n")
            # already-merged ancestor checks -> not an ancestor.
            if args[:2] == ["merge-base", "--is-ancestor"]:
                return FakeRun(returncode=1)
            # branch-mismatch query returns empty so the runner keeps args.branch.
            if args[:2] == ["branch", "--show-current"]:
                return FakeRun(returncode=0, stdout="")
            # fetch is a no-op.
            return FakeRun(returncode=0)

        monkeypatch.setattr(merge_worktree, "_run_git", fake_run_git)

    def test_runner_returns_zero_when_retry_clears_block(
        self, monkeypatch, stale_lock_repo
    ):
        repo = stale_lock_repo["repo"]
        messages: list[str] = []
        ctx = self._build_context(repo)
        self._install_pre_lock_stubs(monkeypatch, ctx, messages)

        # First check returns a block, second returns None -> proceed to acquire.
        check_calls = {"n": 0}

        def fake_check():
            check_calls["n"] += 1
            if check_calls["n"] == 1:
                return "Merge lock held by session 99999-1 on branch 'STALE-LOCK-BRANCH'"
            return None

        from yoke_core.domain import merge_lock as ml

        monkeypatch.setattr(ml, "check", fake_check)

        acquired: list = []

        class FakeHandle:
            session_id = "test-session"
            branch = "STALE-LOCK-BRANCH"

        def fake_acquire(branch, epic_id=None, **_kw):
            acquired.append((branch, epic_id))
            return FakeHandle()

        released: list = []
        monkeypatch.setattr(ml, "acquire", fake_acquire)
        monkeypatch.setattr(
            ml,
            "release",
            lambda handle, **_kw: released.append(handle.session_id),
        )

        # No real sleep delay.
        sleeps: list[float] = []
        monkeypatch.setattr(merge_worktree_runner.time, "sleep", sleeps.append)

        # Stub the body so the runner returns 0 cleanly after acquire.
        monkeypatch.setattr(merge_worktree, "_emit_merge_event", lambda *a, **kw: None)
        monkeypatch.setattr(merge_worktree, "preflight_checks", lambda c: None)
        monkeypatch.setattr(merge_worktree, "check_and_clean_root_dirty_state", lambda c: None)
        monkeypatch.setattr(merge_worktree, "prune_agent_worktrees", lambda r: None)
        monkeypatch.setattr(merge_worktree, "extract_generated_files", lambda c: [])
        monkeypatch.setattr(merge_worktree, "_pre_merge_integration", lambda c: None)
        monkeypatch.setattr(merge_worktree, "_ensure_target_pushed", lambda c: None)
        monkeypatch.setattr(merge_worktree, "_stash_classify_gate", lambda c: None)
        monkeypatch.setattr(merge_worktree, "trial_merge", lambda c: None)
        monkeypatch.setattr(merge_worktree, "do_rebase_or_merge", lambda c: None)
        monkeypatch.setattr(merge_worktree, "run_tests", lambda c: None)
        monkeypatch.setattr(merge_worktree, "do_pr_merge", lambda c: 0)

        rc = merge_worktree_runner.run(MergeArgs(branch="STALE-LOCK-BRANCH"))
        assert rc == 0
        assert check_calls["n"] == 2
        assert acquired == [("STALE-LOCK-BRANCH", None)]
        assert released == ["test-session"]
        # Sleep was monkeypatched -- no real delay incurred.
        assert sleeps == [MERGE_LOCK_RETRY_DELAYS[0]]

    def test_runner_returns_recoverable_exit_when_budget_exhausted(
        self, monkeypatch, stale_lock_repo
    ):
        repo = stale_lock_repo["repo"]
        messages: list[str] = []
        ctx = self._build_context(repo)
        self._install_pre_lock_stubs(monkeypatch, ctx, messages)

        from yoke_core.domain import merge_lock as ml

        block_template = "Merge lock held by session 999-{i} on branch 'STALE-LOCK-BRANCH'"
        call_idx = {"n": 0}

        def fake_check():
            call_idx["n"] += 1
            return block_template.format(i=call_idx["n"])

        acquired_called = {"yes": False}

        def fake_acquire(*a, **kw):
            acquired_called["yes"] = True
            raise AssertionError("acquire must not be called when retries are exhausted")

        monkeypatch.setattr(ml, "check", fake_check)
        monkeypatch.setattr(ml, "acquire", fake_acquire)

        sleeps: list[float] = []
        monkeypatch.setattr(merge_worktree_runner.time, "sleep", sleeps.append)

        rc = merge_worktree_runner.run(MergeArgs(branch="STALE-LOCK-BRANCH"))

        assert rc == RECOVERABLE_MERGE_LOCK_EXIT_CODE
        assert acquired_called["yes"] is False
        # Initial check + one per delay in the schedule.
        assert call_idx["n"] == 1 + len(MERGE_LOCK_RETRY_DELAYS)
        # No real sleep delay.
        assert sleeps == list(MERGE_LOCK_RETRY_DELAYS)
        # Final block message and recovery line both surfaced on stderr.
        final_block = block_template.format(i=call_idx["n"])
        assert any(final_block in m for m in messages)
        assert any(
            "retryable merge-lock condition" in m and "STALE-LOCK-BRANCH" in m
            for m in messages
        )
        assert any(
            "pre-acquire retry budget exhausted" in m for m in messages
        )
