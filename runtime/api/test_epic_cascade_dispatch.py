"""Tests for yoke_core.domain.epic — cascade_task_status and dispatch chains."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import epic
from runtime.api.conftest import insert_item, insert_epic_task

# Synthetic test epic ID — not a real backlog item reference.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@pytest.fixture
def db(test_db):
    return test_db


@pytest.fixture
def db_with_task(db):
    insert_epic_task(db, epic_id=TEST_ITEM_ID, task_num=1, title="First task", status="planning")
    return db


@pytest.fixture
def db_with_chain(db_with_task):
    """DB with a dispatch chain for testing advance logic."""
    queue = json.dumps([1, 2, 3])
    p = _p(db_with_task)
    db_with_task.execute(
        """INSERT INTO epic_dispatch_chains
           (epic_id, worktree, queue, current_index, current_task,
            current_attempt, max_attempts, no_chain, started_at, last_updated)
           VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})""".format(
               p=p
           ),
        (TEST_ITEM_ID, TEST_ITEM_REF, queue, 0, "1", 1, 5, 0, "", ""),
    )
    db_with_task.commit()
    return db_with_task


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
        assert [row["status"] for row in rows] == ["plan-drafted", "plan-drafted", "plan-drafted"]
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
        assert parts[2] == TEST_ITEM_REF
        assert parts[3] == "/tmp/wt"

    def test_get_not_found(self, db):
        with pytest.raises(LookupError, match="not found"):
            epic.dispatch_chain_get(db, "42", TEST_ITEM_REF)

    def test_update_field(self, db_with_chain):
        epic.dispatch_chain_update(db_with_chain, "42", TEST_ITEM_REF, "current_task", "2")
        row = db_with_chain.execute(
            f"SELECT current_task FROM epic_dispatch_chains WHERE epic_id='{TEST_ITEM_ID}' AND worktree='{TEST_ITEM_REF}'"
        ).fetchone()
        assert row["current_task"] == "2"

    def test_update_invalid_field(self, db_with_chain):
        with pytest.raises(ValueError, match="invalid field"):
            epic.dispatch_chain_update(db_with_chain, "42", TEST_ITEM_REF, "bogus", "x")

    def test_list(self, db_with_chain):
        result = epic.dispatch_chain_list(db_with_chain, "42")
        assert TEST_ITEM_REF in result


class TestDispatchChainAdvance:
    def test_advance_increments_index(self, db_with_chain):
        result = epic.dispatch_chain_advance(db_with_chain, "42", TEST_ITEM_REF)
        assert result == "1|2"

        # Verify DB state
        row = db_with_chain.execute(
            f"SELECT current_index, current_task FROM epic_dispatch_chains WHERE epic_id='{TEST_ITEM_ID}' AND worktree='{TEST_ITEM_REF}'"
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
        db_with_task.execute(
            """INSERT INTO epic_dispatch_chains
               (epic_id, worktree, queue, current_index, current_task)
               VALUES ({p}, {p}, {p}, {p}, {p})""".format(p=p),
            (42, "wt", "10,20,30", 0, "10"),
        )
        db_with_task.commit()
        result = epic.dispatch_chain_advance(db_with_task, "42", "wt")
        assert result == "1|20"


class TestDispatchChainRefreshForActivation:
    """Conduct's S6f activation refreshes the chain row so telemetry and
    scheduler views see a fresh ``(current_task, current_attempt,
    last_updated)`` triple. Without this refresh, the chain row carries
    the prior plan-sync's stale values."""

    def _seed_stale_chain(self, db):
        """Insert a chain row with yesterday's last_updated + current_attempt=0."""
        p = _p(db)
        db.execute(
            """INSERT INTO epic_dispatch_chains
               (epic_id, worktree, queue, current_index, current_task,
                current_attempt, max_attempts, no_chain, started_at,
                last_updated)
               VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})""".format(
                   p=p
               ),
            (
                TEST_ITEM_ID,
                "YOK-42-lane",
                json.dumps(["1"]),
                0,
                "1",
                0,  # stale attempt counter from a prior sync
                5,
                0,
                "",
                "2025-01-01T00:00:00Z",  # yesterday
            ),
        )
        db.commit()

    def test_refresh_propagates_dispatch_attempts_to_chain(self, db_with_task):
        """Reads epic_tasks.dispatch_attempts as the honest attempt counter
        and stamps it onto the chain row alongside a fresh last_updated."""
        self._seed_stale_chain(db_with_task)
        p = _p(db_with_task)
        db_with_task.execute(
            "UPDATE epic_tasks SET dispatch_attempts=3 "
            f"WHERE epic_id={p} AND task_num={p}",
            (str(TEST_ITEM_ID), 1),
        )
        db_with_task.commit()

        result = epic.dispatch_chain_refresh_for_activation(
            db_with_task, str(TEST_ITEM_ID), "YOK-42-lane", "1",
        )

        assert "task 1" in result
        assert "attempt 3" in result
        row = db_with_task.execute(
            "SELECT current_task, current_attempt, last_updated "
            "FROM epic_dispatch_chains "
            f"WHERE epic_id={p} AND worktree={p}",
            (str(TEST_ITEM_ID), "YOK-42-lane"),
        ).fetchone()
        assert row["current_task"] == "1"
        assert row["current_attempt"] == 3
        assert row["last_updated"] != "2025-01-01T00:00:00Z"
        assert row["last_updated"].endswith("Z")

    def test_refresh_writes_current_task_when_chain_points_elsewhere(
        self, db_with_task,
    ):
        """A re-activation that re-targets a different task within the
        same worktree (rare but supported by single-task-per-chain shape)
        rewrites current_task on the chain row idempotently."""
        self._seed_stale_chain(db_with_task)
        insert_epic_task(
            db_with_task, epic_id=TEST_ITEM_ID, task_num=2,
            title="Second task", status="planned",
        )
        p = _p(db_with_task)
        db_with_task.execute(
            "UPDATE epic_tasks SET dispatch_attempts=1 "
            f"WHERE epic_id={p} AND task_num={p}",
            (str(TEST_ITEM_ID), 2),
        )
        db_with_task.commit()

        epic.dispatch_chain_refresh_for_activation(
            db_with_task, str(TEST_ITEM_ID), "YOK-42-lane", "2",
        )

        row = db_with_task.execute(
            "SELECT current_task, current_attempt FROM epic_dispatch_chains "
            f"WHERE epic_id={p} AND worktree={p}",
            (str(TEST_ITEM_ID), "YOK-42-lane"),
        ).fetchone()
        assert row["current_task"] == "2"
        assert row["current_attempt"] == 1

    def test_refresh_defaults_attempt_to_one_when_dispatch_attempts_unset(
        self, db_with_task,
    ):
        """epic_tasks.dispatch_attempts defaults to 0 in the schema; the
        refresh treats falsy values as attempt 1 to keep the receipt-binding
        read away from current_attempt=0 (the stale-row signature)."""
        self._seed_stale_chain(db_with_task)
        p = _p(db_with_task)
        db_with_task.execute(
            "UPDATE epic_tasks SET dispatch_attempts=0 "
            f"WHERE epic_id={p} AND task_num={p}",
            (str(TEST_ITEM_ID), 1),
        )
        db_with_task.commit()

        epic.dispatch_chain_refresh_for_activation(
            db_with_task, str(TEST_ITEM_ID), "YOK-42-lane", "1",
        )

        row = db_with_task.execute(
            "SELECT current_attempt FROM epic_dispatch_chains "
            f"WHERE epic_id={p} AND worktree={p}",
            (str(TEST_ITEM_ID), "YOK-42-lane"),
        ).fetchone()
        assert row["current_attempt"] == 1

    def test_refresh_raises_when_chain_row_missing(self, db_with_task):
        with pytest.raises(LookupError, match="dispatch chain"):
            epic.dispatch_chain_refresh_for_activation(
                db_with_task, str(TEST_ITEM_ID), "missing-lane", "1",
            )

    def test_refresh_raises_when_task_row_missing(self, db):
        p = _p(db)
        db.execute(
            """INSERT INTO epic_dispatch_chains
               (epic_id, worktree, queue, current_index, current_task,
                current_attempt, max_attempts, no_chain, started_at,
                last_updated)
               VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})""".format(
                   p=p
               ),
            (
                TEST_ITEM_ID, "YOK-42-lane", json.dumps(["9"]),
                0, "9", 0, 5, 0, "", "2025-01-01T00:00:00Z",
            ),
        )
        db.commit()
        with pytest.raises(LookupError, match="epic_tasks row"):
            epic.dispatch_chain_refresh_for_activation(
                db, str(TEST_ITEM_ID), "YOK-42-lane", "9",
            )
