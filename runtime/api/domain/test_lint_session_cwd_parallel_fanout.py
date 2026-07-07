"""Parallel fan-out regression for the claim-based session-cwd authority.

Conduct's parallel fan-out (e.g. T2 / T4 / T9 of an epic activated in
the same parent session) holds N work_claims simultaneously, each
resolving to its own claimed worktree path. The lint
(``yoke_core.domain.lint_session_cwd``) validates each tool call's
target against the full claimed-worktree set + control-plane root +
free-path allowlist.

This regression locks in:

* the parent session can write under EVERY claimed worktree (claims
  are independent — no single binding to race over),
* the parent session can read control plane (repo root, excluding
  ``.worktrees/``) freely (no bounce-throughs), and
* unauthorised targets (a fourth worktree the session has no claim on)
  still deny with a clear "no active claim covering this path" reason.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_epic_task,
    seed_epic_task_claim,
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.lint_session_cwd_validate import validate_targets


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


def _seed_session(conn, *, session_id):
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, "
        "offered_at, last_heartbeat) "
        "VALUES (%s, 'claude', 'anthropic', 'test-model', '/tmp', %s, %s)",
        (session_id, now, now),
    )
    conn.commit()


def _seed_fanout(conn, repo):
    """Seed the parallel-fan-out shape: epic 1684 with three
    task lanes (T2/T4/T9), all claimed by the same parent session.
    """
    register_machine_checkout(repo.parent / "machine-config", repo, 1)
    seed_item(conn, item_id=1684, branch=None)
    lanes = [
        (2, "YOK-1684-seed"),
        (4, "YOK-1684-callers-a"),
        (9, "YOK-1684-backfill"),
    ]
    for task_num, branch in lanes:
        seed_epic_task(conn, epic_id=1684, task_num=task_num, branch=branch)
        seed_epic_task_claim(conn, "sid-parent", epic_id=1684, task_num=task_num)
        (repo / ".worktrees" / branch).mkdir(parents=True)


class TestParallelFanoutLint:
    def test_each_claimed_worktree_is_writable(self, conn, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".worktrees").mkdir(parents=True)
        _seed_fanout(conn, repo)

        for branch in (
            "YOK-1684-seed",
            "YOK-1684-callers-a",
            "YOK-1684-backfill",
        ):
            target = repo / ".worktrees" / branch / "src" / "lane.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# stub")
            verdict = validate_targets(
                conn,
                session_id="sid-parent",
                targets=(str(target),),
            )
            assert verdict.allow is True, (
                f"lane {branch} should be writable by the parent session"
            )

    def test_orchestrator_control_plane_reads_pass(self, conn, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".worktrees").mkdir(parents=True)
        _seed_fanout(conn, repo)

        # Reads against the repo root (control plane) — no scope
        # transition needed; under the old envelope, these were blocked.
        for path in (
            repo / "data" / "yoke.db",
            repo / "docs" / "OVERVIEW.md",
            repo / ".agents" / "skills" / "yoke" / "advance" / "SKILL.md",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("stub")
            verdict = validate_targets(
                conn,
                session_id="sid-parent",
                targets=(str(path),),
            )
            assert verdict.allow is True, (
                f"control-plane read of {path} should pass under "
                "claim-based authority"
            )

    def test_unclaimed_worktree_still_denies(self, conn, tmp_path):
        """A fourth worktree the parent does not hold a claim on still
        denies — the safety property the envelope was supposed to give
        but only delivered for whichever lane attached last.
        """
        repo = tmp_path / "repo"
        (repo / ".worktrees").mkdir(parents=True)
        _seed_fanout(conn, repo)
        # Use a synthetic outside-tmp path so the free-path allowlist
        # (which covers /var/folders on macOS) does not authorise it.
        target = "/opt/other-repo/.worktrees/YOK-1684-rogue/file.py"
        verdict = validate_targets(
            conn,
            session_id="sid-parent",
            targets=(target,),
        )
        assert verdict.allow is False
        assert "YOK-1684-rogue" in verdict.offending_target
        assert len(verdict.claims) == 3

    def test_item_level_claim_does_not_grant_sibling_worktrees(
        self, conn, tmp_path,
    ):
        """AC-17: after the hotfix rollback, an item-level claim on an
        epic with sibling-branch task worktrees no longer authorises
        the sibling paths. Only explicit ``target_kind='epic_task'``
        claims grant per-task authority.
        """
        repo = tmp_path / "repo"
        (repo / ".worktrees").mkdir(parents=True)
        register_machine_checkout(repo.parent / "machine-config", repo, 1)
        seed_item(conn, item_id=1872, branch="YOK-1872")
        for task_num, branch in (
            (1, "YOK-1872-substrate"),
            (10, "YOK-1872-propagation"),
        ):
            seed_epic_task(
                conn, epic_id=1872, task_num=task_num, branch=branch,
            )
            (repo / ".worktrees" / branch).mkdir(parents=True)
        (repo / ".worktrees" / "YOK-1872").mkdir(parents=True)
        seed_item_claim(conn, "sid-orch", item_id=1872)

        # Target outside the free-path allowlist so the claim gate
        # is the decisive surface.
        rogue_target = "/opt/elsewhere/.worktrees/YOK-1872-substrate/x.py"
        verdict = validate_targets(
            conn,
            session_id="sid-orch",
            targets=(rogue_target,),
        )
        assert verdict.allow is False
        # The session's only resolved authority is items.worktree
        # itself — exactly one row, no sibling inheritance.
        assert len(verdict.claims) == 1
        assert verdict.claims[0].task_num is None
        assert verdict.claims[0].worktree_path == str(
            repo / ".worktrees" / "YOK-1872"
        )


class TestUnclaimedSessionLint:
    """Sessions that hold no work-claims of their own fall through to allow.

    Codex subagent dispatch shares the parent's ``session_id``, so its
    tool calls land on the parent's claim directly without any
    identity propagation; this class covers the no-direct-claim path.
    """

    def test_unclaimed_session_falls_through_to_allow(
        self, conn, tmp_path,
    ):
        repo = tmp_path / "repo"
        (repo / ".worktrees").mkdir(parents=True)
        _seed_fanout(conn, repo)
        _seed_session(conn, session_id="sid-detached")
        verdict = validate_targets(
            conn,
            session_id="sid-detached",
            targets=("/opt/anywhere/file.py",),
        )
        assert verdict.allow is True
