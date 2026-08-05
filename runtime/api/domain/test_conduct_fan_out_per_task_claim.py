"""Integration test for conduct fan-out per-task work-claim lifecycle.

Exercises acquire → resolve → lint-authorise →
release across multi-worktree and same-worktree fan-out shapes. The
test simulates conduct's claim lifecycle with a disposable-Postgres DB
double and direct DB writes; the handler-level acquire/release coverage lives in
``runtime/api/domain/handlers/``.
"""

from __future__ import annotations

from runtime.api.domain.conduct_fan_out_claim_test_support import (
    conn as conn,
    ensure_item_worktree as _ensure_item_worktree,
    release_claim as _release,
    seed_fanout as _seed_fanout,
    write_target as _write_target,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain.lint_session_cwd_validate import validate_targets
from yoke_core.domain.session_claimed_worktrees import claimed_worktrees


# Multi-worktree case: >=2 distinct worktree paths across tasks.


class TestMultiWorktreeFanOutLifecycle:
    LANES = (
        (1, "YOK-1872-substrate"),
        (10, "YOK-1872-propagation"),
        (20, "YOK-1872-integration"),
    )

    def test_n_claims_materialise_before_dispatch(self, conn, tmp_path):
        # N task worktrees produce N epic_task claim rows.
        _seed_fanout(
            conn,
            tmp_path / "repo",
            item_id=1872,
            session_id="sid-orch",
            lanes=self.LANES,
        )
        active = conn.execute(
            "SELECT epic_id, task_num FROM work_claims "
            "WHERE session_id='sid-orch' AND target_kind='epic_task' "
            "AND released_at IS NULL ORDER BY task_num"
        ).fetchall()
        assert [(r["epic_id"], r["task_num"]) for r in active] == [
            (1872, 1),
            (1872, 10),
            (1872, 20),
        ]

    def test_each_claim_resolves_to_its_task_worktree(self, conn, tmp_path):
        # Each claim resolves through the task's linked universal lane.
        repo = tmp_path / "repo"
        _seed_fanout(
            conn,
            repo,
            item_id=1872,
            session_id="sid-orch",
            lanes=self.LANES,
        )
        resolved = claimed_worktrees(conn, session_id="sid-orch")
        assert [(c.task_num, c.worktree_path) for c in resolved] == [
            (1, str(repo / ".worktrees" / "YOK-1872-substrate")),
            (10, str(repo / ".worktrees" / "YOK-1872-propagation")),
            (20, str(repo / ".worktrees" / "YOK-1872-integration")),
        ]

    def test_lint_authorises_each_task_worktree(self, conn, tmp_path):
        # No WORKTREE-BINDING REFUSAL per dispatched subagent.
        repo = tmp_path / "repo"
        _seed_fanout(
            conn,
            repo,
            item_id=1872,
            session_id="sid-orch",
            lanes=self.LANES,
        )
        for _tn, branch in self.LANES:
            target = _write_target(repo, branch)
            verdict = validate_targets(
                conn,
                session_id="sid-orch",
                targets=(str(target),),
            )
            assert verdict.allow is True, (
                f"lane {branch} should be writable; got: {verdict}"
            )

    def test_release_clears_authority_per_task(self, conn, tmp_path):
        # released_at set; resolver drops the released lane
        # while sibling lanes remain. (validate_targets cannot assert
        # denial here because pytest tmp_path lands under the lint's
        # free-path allowlist; the resolver is the semantic authority.)
        repo = tmp_path / "repo"
        claims = _seed_fanout(
            conn,
            repo,
            item_id=1872,
            session_id="sid-orch",
            lanes=self.LANES,
        )
        _release(conn, claims[10])
        row = conn.execute(
            "SELECT released_at FROM work_claims WHERE id = %s",
            (claims[10],),
        ).fetchone()
        assert row["released_at"] is not None
        resolved_paths = [
            c.worktree_path for c in claimed_worktrees(conn, session_id="sid-orch")
        ]
        prop = str(repo / ".worktrees" / "YOK-1872-propagation")
        substrate = str(repo / ".worktrees" / "YOK-1872-substrate")
        integration = str(repo / ".worktrees" / "YOK-1872-integration")
        assert prop not in resolved_paths
        assert substrate in resolved_paths
        assert integration in resolved_paths
        # Sibling lane still passes the lint.
        allowed = _write_target(repo, "YOK-1872-substrate")
        assert (
            validate_targets(
                conn,
                session_id="sid-orch",
                targets=(str(allowed),),
            ).allow
            is True
        )
        # A worktree the session never claimed and that lives outside
        # the free-path allowlist still denies — proves the per-task
        # claim shape is the only authority gate (no inheritance).
        rogue = "/opt/other-repo/.worktrees/YOK-1872-rogue/x.py"
        verdict = validate_targets(
            conn,
            session_id="sid-orch",
            targets=(rogue,),
        )
        assert verdict.allow is False
        assert "YOK-1872-rogue" in verdict.offending_target

    def test_full_release_clears_all_authority(self, conn, tmp_path):
        repo = tmp_path / "repo"
        claims = _seed_fanout(
            conn,
            repo,
            item_id=1872,
            session_id="sid-orch",
            lanes=self.LANES,
        )
        for cid in claims.values():
            _release(conn, cid)
        assert claimed_worktrees(conn, session_id="sid-orch") == []


# Same-worktree case: multiple tasks share one branch.
class TestSameWorktreeFanOutLifecycle:
    LANES = (
        (5, "YOK-1873-shared"),
        (6, "YOK-1873-shared"),
    )

    def test_two_claims_one_worktree_authorise_path(self, conn, tmp_path):
        repo = tmp_path / "repo"
        _seed_fanout(
            conn,
            repo,
            item_id=1873,
            session_id="sid-orch",
            lanes=self.LANES,
        )
        resolved = claimed_worktrees(conn, session_id="sid-orch")
        assert len(resolved) == 2
        shared = str(repo / ".worktrees" / "YOK-1873-shared")
        assert all(c.worktree_path == shared for c in resolved)
        target = _write_target(repo, "YOK-1873-shared")
        assert (
            validate_targets(
                conn,
                session_id="sid-orch",
                targets=(str(target),),
            ).allow
            is True
        )

    def test_release_one_keeps_authority_via_sibling(self, conn, tmp_path):
        # Conduct may release one task's claim while the sibling stays
        # active; shared worktree stays authorised through the survivor.
        repo = tmp_path / "repo"
        claims = _seed_fanout(
            conn,
            repo,
            item_id=1873,
            session_id="sid-orch",
            lanes=self.LANES,
        )
        _release(conn, claims[5])
        target = _write_target(repo, "YOK-1873-shared")
        assert (
            validate_targets(
                conn,
                session_id="sid-orch",
                targets=(str(target),),
            ).allow
            is True
        )

    def test_release_both_clears_authority(self, conn, tmp_path):
        # Releasing every per-task claim drains the session's resolver
        # surface — claimed_worktrees returns no rows. (The lint's
        # no-claims branch short-circuits to allow=True so the resolver
        # is the semantic authority here.)
        repo = tmp_path / "repo"
        claims = _seed_fanout(
            conn,
            repo,
            item_id=1873,
            session_id="sid-orch",
            lanes=self.LANES,
        )
        for cid in claims.values():
            _release(conn, cid)
        assert claimed_worktrees(conn, session_id="sid-orch") == []


# Item + epic_task coexistence — no sibling inheritance.
class TestItemAndEpicTaskClaimsCoexist:
    def test_both_claims_coexist_and_authorise_correctly(
        self,
        conn,
        tmp_path,
    ):
        repo = tmp_path / "repo"
        conn.execute(
            "INSERT INTO projects (id, slug) VALUES (1, 'yoke')",
        )
        register_machine_checkout(repo.parent / "machine-config", repo, 1)
        conn.execute("INSERT INTO items (id, project_id) VALUES (1872, 1)")
        _ensure_item_worktree(
            conn,
            item_id=1872,
            branch="YOK-1872",
            lane_role="implementation",
            repo=repo,
        )
        worker_lane_id = _ensure_item_worktree(
            conn,
            item_id=1872,
            branch="YOK-1872-substrate",
            lane_role="worker",
            repo=repo,
        )
        conn.execute(
            "INSERT INTO epic_tasks "
            "(epic_id, task_num, item_worktree_id) VALUES (1872, 1, %s)",
            (worker_lane_id,),
        )
        for branch in ("YOK-1872", "YOK-1872-substrate"):
            (repo / ".worktrees" / branch).mkdir(parents=True, exist_ok=True)
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id) "
            "VALUES ('sid-orch', 'item', 1872)"
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, epic_id, "
            "task_num) VALUES ('sid-orch', 'epic_task', 1872, 1)"
        )
        conn.commit()
        paths = sorted(
            c.worktree_path for c in claimed_worktrees(conn, session_id="sid-orch")
        )
        assert str(repo / ".worktrees" / "YOK-1872") in paths
        assert str(repo / ".worktrees" / "YOK-1872-substrate") in paths
