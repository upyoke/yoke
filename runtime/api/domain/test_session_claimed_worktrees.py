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

import json
import os
from pathlib import Path

import pytest

from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree, claimed_worktrees
from yoke_core.domain.work_claim_targets import WorkClaimTarget, make_epic_task_target, make_item_target
from runtime.api.engines._doctor_native_sql_test_helpers import connect_disposable_test_db


_TEST_REPO_ROOT_ENV = "YOKE_TEST_SESSION_CLAIMED_REPO_ROOT"


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = tmp_path / "repo" / "yoke"
    repo_root.mkdir(parents=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"projects": {str(repo_root): {"project_id": 1}}}), encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
    monkeypatch.setenv(_TEST_REPO_ROOT_ENV, str(repo_root))
    c = connect_disposable_test_db()
    execute_schema_script(
        c,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL,
            branch TEXT NOT NULL,
            path TEXT,
            lane_role TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            released_at TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER NOT NULL,
            task_num INTEGER NOT NULL,
            item_worktree_id INTEGER,
            PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            released_at TEXT
        );
        INSERT INTO projects (id, slug) VALUES (1, 'yoke');
        """,
    )
    c.commit()
    yield c
    c.close()


def _project_id(project="yoke") -> int:
    return {"yoke": 1, "externalwebapp": 2}.get(project, 100)


def _worktree_path(branch: str) -> str:
    return str(Path(os.environ[_TEST_REPO_ROOT_ENV]) / ".worktrees" / branch)


def _seed_item(conn, *, item_id, worktree=None, project="yoke"):
    conn.execute("INSERT INTO items (id, project_id) VALUES (%s, %s)", (item_id, _project_id(project)))
    if worktree:
        conn.execute(
            "INSERT INTO item_worktrees "
            "(item_id, branch, path, lane_role, state, created_at, "
            "updated_at) "
            "VALUES (%s, %s, %s, 'implementation', 'active', %s, %s)",
            (item_id, worktree, _worktree_path(worktree), "2026-05-14T12:00:00Z", "2026-05-14T12:00:00Z"),
        )
    conn.commit()


def _seed_epic_task(conn, *, epic_id, task_num, worktree):
    row = conn.execute(
        "INSERT INTO item_worktrees "
        "(item_id, branch, path, lane_role, state, created_at, updated_at) "
        "VALUES (%s, %s, %s, 'worker', 'active', %s, %s) RETURNING id",
        (epic_id, worktree, _worktree_path(worktree), "2026-05-14T12:00:00Z", "2026-05-14T12:00:00Z"),
    ).fetchone()
    lane_id = int(row["id"] if hasattr(row, "keys") else row[0])
    conn.execute("INSERT INTO epic_tasks (epic_id, task_num, item_worktree_id) VALUES (%s, %s, %s)", (epic_id, task_num, lane_id))
    conn.commit()


def _seed_lane(conn, *, item_id, worktree, role):
    conn.execute(
        "INSERT INTO item_worktrees (item_id, branch, path, lane_role, state, created_at, updated_at) VALUES (%s, %s, %s, %s, 'active', %s, %s)",
        (item_id, worktree, _worktree_path(worktree), role, "2026-05-14T12:00:00Z", "2026-05-14T12:00:00Z"),
    )
    conn.commit()


def _seed_claim(conn, *, session_id, target_kind, item_id=None, epic_id=None, task_num=None, released_at=None):
    target = make_item_target(item_id) if target_kind == "item" else make_epic_task_target(epic_id, task_num)
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, released_at) VALUES (%s, %s, %s, %s)",
        (session_id, target_kind, target.scope_json(), released_at),
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
        assert result == [ClaimedWorktree(item_id=1691, task_num=None, worktree_path=_worktree_path("YOK-1691"))]

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
            _seed_claim(conn, session_id="sid-parent", target_kind="epic_task", epic_id=1684, task_num=tnum)
        result = claimed_worktrees(conn, session_id="sid-parent")
        assert [c.task_num for c in result] == [2, 4, 9]
        assert [c.worktree_path for c in result] == [_worktree_path("YOK-1684-seed"), _worktree_path("YOK-1684-callers-a"), _worktree_path("YOK-1684-backfill")]
        # Single session, three claimed worktrees — the parallel
        # fan-out shape that motivated the rewrite.


class TestReleasedClaimsExcluded:
    def test_released_claim_is_skipped(self, conn):
        _seed_item(conn, item_id=1691, worktree="YOK-1691")
        _seed_claim(conn, session_id="sid-1", target_kind="item", item_id=1691, released_at="2026-05-14T12:00:00Z")
        assert claimed_worktrees(conn, session_id="sid-1") == []

    def test_mixed_active_and_released(self, conn):
        _seed_item(conn, item_id=1000, worktree="YOK-1000")
        _seed_item(conn, item_id=1001, worktree="YOK-1001")
        _seed_claim(conn, session_id="sid-x", target_kind="item", item_id=1000, released_at="2026-05-13T00:00:00Z")
        _seed_claim(conn, session_id="sid-x", target_kind="item", item_id=1001)
        result = claimed_worktrees(conn, session_id="sid-x")
        assert [c.item_id for c in result] == [1001]


class TestProcessTargetKind:
    def test_process_claim_has_no_worktree(self, conn):
        # target_kind='process' claims (scheduler runs, doctor lanes)
        # have no worktree concept; they contribute nothing.
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope) VALUES ('sid-1', 'process', %s)",
            (WorkClaimTarget("process", {"process_key": "doctor-run-1", "conflict_group": "doctor-run-1"}).scope_json(),),
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
        assert [c.worktree_path for c in result] == [_worktree_path("lane-hooks"), _worktree_path("lane-relay"), _worktree_path("lane-integration")]
        assert {(c.item_id, c.task_num) for c in result} == {(500, None)}

    def test_released_lane_is_excluded(self, conn):
        _seed_item(conn, item_id=501, worktree=None)
        _seed_lane(conn, item_id=501, worktree="lane-live", role="worker")
        _seed_lane(conn, item_id=501, worktree="lane-gone", role="worker")
        conn.execute("UPDATE item_worktrees SET released_at = %s WHERE branch = %s", ("2026-05-14T13:00:00Z", "lane-gone"))
        conn.commit()
        _seed_claim(conn, session_id="sid-1", target_kind="item", item_id=501)
        assert [c.worktree_path for c in claimed_worktrees(conn, session_id="sid-1")] == [_worktree_path("lane-live")]

    def test_epic_item_claim_includes_task_lanes(self, conn):
        # Task lanes are recorded under the epic's item_id, so the epic's
        # own claim covers them; the per-task claim stays task-scoped.
        _seed_item(conn, item_id=700, worktree="epic-main")
        _seed_epic_task(conn, epic_id=700, task_num=1, worktree="epic-task-1")
        _seed_claim(conn, session_id="sid-orch", target_kind="item", item_id=700)
        assert [c.worktree_path for c in claimed_worktrees(conn, session_id="sid-orch")] == [_worktree_path("epic-main"), _worktree_path("epic-task-1")]
