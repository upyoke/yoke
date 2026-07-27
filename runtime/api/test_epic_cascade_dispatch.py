"""Tests for yoke_core.domain.epic — cascade_task_status and dispatch chains."""

from __future__ import annotations

import pytest

from yoke_core.domain import epic
from runtime.api.conftest import insert_item, insert_epic_task
from runtime.api.fixtures.backlog import insert_item_worktree

from runtime.api.epic_cascade_dispatch_test_support import (
    _p,
    db as db,
    db_with_chain as db_with_chain,
    db_with_task as db_with_task,
    TEST_ITEM_ID,
    TEST_ITEM_REF,
)


class TestCascadeTaskStatus:
    def test_forward_cascade_updates_tasks(self, db):
        insert_item(db, id=42, type="epic", status="planning", project="yoke")
        insert_epic_task(db, epic_id=42, task_num=1, title="Task 1", status="planning")
        insert_epic_task(db, epic_id=42, task_num=2, title="Task 2", status="planning")
        insert_epic_task(db, epic_id=42, task_num=3, title="Task 3", status="planning")

        result = epic.cascade_task_status(db, "42", "planning", "plan-drafted")

        assert result == "3"
        rows = db.execute(
            "SELECT task_num, status, last_heartbeat FROM epic_tasks WHERE epic_id='42' ORDER BY task_num"
        ).fetchall()
        assert [row["status"] for row in rows] == [
            "plan-drafted",
            "plan-drafted",
            "plan-drafted",
        ]
        assert all(row["last_heartbeat"].endswith("Z") for row in rows)

    def test_exceptional_states_are_preserved(self, db):
        insert_item(db, id=42, type="epic", status="planned", project="yoke")
        insert_epic_task(db, epic_id=42, task_num=1, title="Task 1", status="planned")
        insert_epic_task(db, epic_id=42, task_num=2, title="Task 2", status="blocked")
        insert_epic_task(db, epic_id=42, task_num=3, title="Task 3", status="failed")

        result = epic.cascade_task_status(db, "42", "planned", "plan-drafted")

        assert result == "1"
        rows = db.execute(
            "SELECT task_num, status FROM epic_tasks WHERE epic_id='42' ORDER BY task_num"
        ).fetchall()
        assert [row["status"] for row in rows] == ["plan-drafted", "blocked", "failed"]

    def test_unknown_transition_returns_zero(self, db):
        insert_item(db, id=42, type="epic", status="planned", project="yoke")
        insert_epic_task(db, epic_id=42, task_num=1, title="Task 1", status="planned")

        result = epic.cascade_task_status(db, "42", "planned", "implementing")

        assert result == "0"
        row = db.execute(
            "SELECT status FROM epic_tasks WHERE epic_id='42' AND task_num=1"
        ).fetchone()
        assert row["status"] == "planned"


class TestDispatchChain:
    def test_upsert_and_get(self, db_with_task):
        data = {
            "worktree_path": "/tmp/wt",
            "queue": [1, 2, 3],
            "current_index": 0,
            "current_task": "1",
            "current_attempt": 1,
            "max_attempts": 5,
            "no_chain": 0,
            "started_at": "2025-01-01T00:00:00Z",
        }
        epic.dispatch_chain_upsert(db_with_task, "42", TEST_ITEM_REF, data)
        result = epic.dispatch_chain_get(db_with_task, "42", TEST_ITEM_REF)
        parts = result.split("|")
        assert parts[1] == "42"
        lane = db_with_task.execute(
            "SELECT id, path FROM item_worktrees WHERE item_id=42 AND branch='YOK-42'"
        ).fetchone()
        assert parts[2] == str(lane["id"])
        assert lane["path"] == "/tmp/wt"

    def test_get_not_found(self, db):
        with pytest.raises(LookupError, match="not found"):
            epic.dispatch_chain_get(db, "42", TEST_ITEM_REF)

    def test_update_field(self, db_with_chain):
        epic.dispatch_chain_update(
            db_with_chain, "42", TEST_ITEM_REF, "current_task", "2"
        )
        row = db_with_chain.execute(
            "SELECT c.current_task FROM epic_dispatch_chains c "
            "JOIN item_worktrees iw ON iw.id=c.item_worktree_id "
            f"WHERE c.epic_id='{TEST_ITEM_ID}' AND iw.branch='{TEST_ITEM_REF}'"
        ).fetchone()
        assert row["current_task"] == "2"

    def test_update_invalid_field(self, db_with_chain):
        with pytest.raises(ValueError, match="invalid field"):
            epic.dispatch_chain_update(db_with_chain, "42", TEST_ITEM_REF, "bogus", "x")

    def test_list(self, db_with_chain):
        result = epic.dispatch_chain_list(db_with_chain, "42")
        lane_id = db_with_chain.execute(
            "SELECT id FROM item_worktrees WHERE item_id=42 AND branch='YOK-42'"
        ).fetchone()["id"]
        assert str(lane_id) in result.split("|")


class TestDispatchChainAdvance:
    def test_advance_increments_index(self, db_with_chain):
        result = epic.dispatch_chain_advance(db_with_chain, "42", TEST_ITEM_REF)
        assert result == "1|2"

        # Verify DB state
        row = db_with_chain.execute(
            "SELECT c.current_index, c.current_task FROM epic_dispatch_chains c "
            "JOIN item_worktrees iw ON iw.id=c.item_worktree_id "
            f"WHERE c.epic_id='{TEST_ITEM_ID}' AND iw.branch='{TEST_ITEM_REF}'"
        ).fetchone()
        assert row["current_index"] == 1
        assert row["current_task"] == "2"

    def test_advance_to_end(self, db_with_chain):
        # Advance twice (0->1, 1->2)
        epic.dispatch_chain_advance(db_with_chain, "42", TEST_ITEM_REF)
        epic.dispatch_chain_advance(db_with_chain, "42", TEST_ITEM_REF)

        # Now at index 2, queue has 3 items -> end of queue
        with pytest.raises(IndexError, match="end of queue"):
            epic.dispatch_chain_advance(db_with_chain, "42", TEST_ITEM_REF)

    def test_advance_not_found(self, db):
        with pytest.raises(LookupError, match="not found"):
            epic.dispatch_chain_advance(db, "42", "missing")

    def test_advance_csv_queue(self, db_with_task):
        """Queue stored as CSV string instead of JSON array."""
        p = _p(db_with_task)
        lane = insert_item_worktree(
            db_with_task,
            item_id=TEST_ITEM_ID,
            branch="wt",
            lane_role="worker",
        )
        db_with_task.execute(
            """INSERT INTO epic_dispatch_chains
               (epic_id, item_worktree_id, queue, current_index, current_task)
               VALUES ({p}, {p}, {p}, {p}, {p})""".format(p=p),
            (42, lane["id"], "10,20,30", 0, "10"),
        )
        db_with_task.commit()
        result = epic.dispatch_chain_advance(db_with_task, "42", "wt")
        assert result == "1|20"
