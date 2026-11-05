"""Tests for :func:`session_claimed_worktrees.claimed_worktrees`.

Covers the shape rules:

* Empty-claim session returns ``[]``.
* A ``target_kind='item'`` claim returns every active lane recorded
  under its item, in lane id order, whatever the lane role.
* Multi-claim epic (``target_kind='epic_task'``) enumerates per-task
  worktrees, one row per task, each resolved through that task's own
  ``epic_tasks.item_worktree_id`` rather than widened to the epic.
* Released claims and released lanes are both excluded.

Every lane here is seeded WITH its ``path`` column populated, because
that column is the authority the resolver reads. A lane row with a null
path models no universe worktree preparation can produce, and seeding
one would let the resolver silently return no authority at all while
the test still looked meaningful.

The fixture uses a disposable Postgres database and seeds only the
columns the resolver reads — no need to materialise the full Yoke schema.
"""

from __future__ import annotations

from runtime.api.domain.session_claimed_worktrees_test_support import (
    _TEST_REPO_ROOT_ENV as _TEST_REPO_ROOT_ENV,
    _project_id as _project_id,
    _seed_claim as _seed_claim,
    _seed_epic_task as _seed_epic_task,
    _seed_item as _seed_item,
    _worktree_path as _worktree_path,
    conn as conn,
)


from yoke_contracts.timestamps import parse_instant


from yoke_core.domain.session_claimed_worktrees import (
    ClaimedWorktree,
    claimed_worktrees,
)
from yoke_core.domain.work_claim_targets import (
    WorkClaimTarget,
)


def _seed_lane(conn, *, item_id, worktree, role):
    conn.execute(
        "INSERT INTO item_worktrees (item_id, branch, path, lane_role, state, created_at, updated_at) VALUES (%s, %s, %s, %s, 'active', %s, %s)",
        (
            item_id,
            worktree,
            _worktree_path(worktree),
            role,
            parse_instant("2026-05-14T12:00:00Z"),
            parse_instant("2026-05-14T12:00:00Z"),
        ),
    )
    conn.commit()


class TestEmptySession:
    def test_no_claims_returns_empty(self, conn):
        assert claimed_worktrees(conn, session_id="sid-empty") == []

    def test_blank_session_id_returns_empty(self, conn):
        assert claimed_worktrees(conn, session_id="") == []


class TestSingleItemClaim:
    def test_item_claim_returns_recorded_lane_path(self, conn):
        _seed_item(conn, item_id=1691, worktree="YOK-1691")
        _seed_claim(conn, session_id="sid-1", target_kind="item", item_id=1691)
        result = claimed_worktrees(conn, session_id="sid-1")
        assert result == [
            ClaimedWorktree(
                item_id=1691, task_num=None, worktree_path=_worktree_path("YOK-1691")
            )
        ]

    def test_item_without_worktree_branch_is_skipped(self, conn):
        # Evidence-only items (--no-worktree) have no active lane row.
        _seed_item(conn, item_id=42, worktree=None)
        _seed_claim(conn, session_id="sid-1", target_kind="item", item_id=42)
        assert claimed_worktrees(conn, session_id="sid-1") == []


class TestMultiTaskEpicClaim:
    def test_per_task_worktrees_enumerated(self, conn):
        # Conduct fan-out: a parent session holds claims on three task
        # lanes of the same epic. Each lane has its own worktree branch.
        _seed_item(conn, item_id=1684, worktree=None)
        _seed_epic_task(conn, epic_id=1684, task_num=2, worktree="YOK-1684-seed")
        _seed_epic_task(conn, epic_id=1684, task_num=4, worktree="YOK-1684-callers-a")
        _seed_epic_task(conn, epic_id=1684, task_num=9, worktree="YOK-1684-backfill")
        for tnum in (2, 4, 9):
            _seed_claim(
                conn,
                session_id="sid-parent",
                target_kind="epic_task",
                epic_id=1684,
                task_num=tnum,
            )
        result = claimed_worktrees(conn, session_id="sid-parent")
        assert [c.task_num for c in result] == [2, 4, 9]
        assert [c.worktree_path for c in result] == [
            _worktree_path("YOK-1684-seed"),
            _worktree_path("YOK-1684-callers-a"),
            _worktree_path("YOK-1684-backfill"),
        ]
        # Single session, three claimed worktrees — the parallel
        # fan-out shape that motivated the rewrite.


class TestReleasedClaimsExcluded:
    def test_released_claim_is_skipped(self, conn):
        _seed_item(conn, item_id=1691, worktree="YOK-1691")
        _seed_claim(
            conn,
            session_id="sid-1",
            target_kind="item",
            item_id=1691,
            released_at="2026-05-14T12:00:00Z",
        )
        assert claimed_worktrees(conn, session_id="sid-1") == []

    def test_mixed_active_and_released(self, conn):
        _seed_item(conn, item_id=1000, worktree="YOK-1000")
        _seed_item(conn, item_id=1001, worktree="YOK-1001")
        _seed_claim(
            conn,
            session_id="sid-x",
            target_kind="item",
            item_id=1000,
            released_at="2026-05-13T00:00:00Z",
        )
        _seed_claim(conn, session_id="sid-x", target_kind="item", item_id=1001)
        result = claimed_worktrees(conn, session_id="sid-x")
        assert [c.item_id for c in result] == [1001]


class TestProcessTargetKind:
    def test_process_claim_has_no_worktree(self, conn):
        # target_kind='process' claims (scheduler runs, doctor lanes)
        # have no worktree concept; they contribute nothing.
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope) VALUES ('sid-1', 'process', %s)",
            (
                WorkClaimTarget(
                    "process",
                    {"process_key": "doctor-run-1", "conflict_group": "doctor-run-1"},
                ).scope_json(),
            ),
        )
        conn.commit()
        assert claimed_worktrees(conn, session_id="sid-1") == []


class TestItemClaimCoversEveryRegisteredLane:
    """An ``item``-level claim authorises every active lane of its item.

    Worker lanes are included: a Blitz registers them beside one
    integration lane under the item itself, and an epic's task lanes are
    recorded under the epic's ``item_id``. Foreign-session protection is
    ``lane_occupancy``'s job, not a narrower authority here.
    """

    def test_item_claim_returns_every_lane_in_lane_order(self, conn):
        _seed_item(conn, item_id=500, worktree=None)
        _seed_lane(conn, item_id=500, worktree="lane-hooks", role="worker")
        _seed_lane(conn, item_id=500, worktree="lane-relay", role="worker")
        _seed_lane(conn, item_id=500, worktree="lane-integration", role="integration")
        _seed_claim(conn, session_id="sid-blitz", target_kind="item", item_id=500)
        result = claimed_worktrees(conn, session_id="sid-blitz")
        assert [c.worktree_path for c in result] == [
            _worktree_path("lane-hooks"),
            _worktree_path("lane-relay"),
            _worktree_path("lane-integration"),
        ]
        assert {(c.item_id, c.task_num) for c in result} == {(500, None)}

    def test_released_lane_is_excluded(self, conn):
        _seed_item(conn, item_id=501, worktree=None)
        _seed_lane(conn, item_id=501, worktree="lane-live", role="worker")
        _seed_lane(conn, item_id=501, worktree="lane-gone", role="worker")
        conn.execute(
            "UPDATE item_worktrees SET released_at = %s WHERE branch = %s",
            (parse_instant("2026-05-14T13:00:00Z"), "lane-gone"),
        )
        conn.commit()
        _seed_claim(conn, session_id="sid-1", target_kind="item", item_id=501)
        assert [
            c.worktree_path for c in claimed_worktrees(conn, session_id="sid-1")
        ] == [_worktree_path("lane-live")]

    def test_epic_item_claim_includes_task_lanes(self, conn):
        # Task lanes are recorded under the epic's item_id, so the epic's
        # own claim covers them; the per-task claim stays task-scoped.
        _seed_item(conn, item_id=700, worktree="epic-main")
        _seed_epic_task(conn, epic_id=700, task_num=1, worktree="epic-task-1")
        _seed_claim(conn, session_id="sid-orch", target_kind="item", item_id=700)
        assert [
            c.worktree_path for c in claimed_worktrees(conn, session_id="sid-orch")
        ] == [_worktree_path("epic-main"), _worktree_path("epic-task-1")]
