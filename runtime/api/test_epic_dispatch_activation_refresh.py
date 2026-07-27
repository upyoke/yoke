"""Dispatch-chain refresh coverage for epic task activation."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import epic
from runtime.api.conftest import insert_epic_task, insert_item
from runtime.api.epic_cascade_dispatch_test_support import (
    TEST_ITEM_ID,
    _p,
    db as db,
    db_with_task as db_with_task,
)
from runtime.api.fixtures.backlog import insert_item_worktree


class TestDispatchChainRefreshForActivation:
    """Activation refreshes the chain row so telemetry and scheduler views
    see a fresh ``(current_task, current_attempt, last_updated)`` triple."""

    def _seed_stale_chain(self, db):
        """Insert a chain row with yesterday's last_updated + current_attempt=0."""
        p = _p(db)
        lane = insert_item_worktree(
            db,
            item_id=TEST_ITEM_ID,
            branch="YOK-42-lane",
            lane_role="worker",
        )
        db.execute(
            """INSERT INTO epic_dispatch_chains
               (epic_id, item_worktree_id, queue, current_index, current_task,
                current_attempt, max_attempts, no_chain, started_at,
                last_updated)
               VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})""".format(p=p),
            (
                TEST_ITEM_ID,
                lane["id"],
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
            db_with_task,
            str(TEST_ITEM_ID),
            "YOK-42-lane",
            "1",
        )

        assert "task 1" in result
        assert "attempt 3" in result
        row = db_with_task.execute(
            "SELECT current_task, current_attempt, last_updated "
            "FROM epic_dispatch_chains c JOIN item_worktrees iw "
            "ON iw.id=c.item_worktree_id "
            f"WHERE c.epic_id={p} AND iw.branch={p}",
            (str(TEST_ITEM_ID), "YOK-42-lane"),
        ).fetchone()
        assert row["current_task"] == "1"
        assert row["current_attempt"] == 3
        assert row["last_updated"] != "2025-01-01T00:00:00Z"
        assert row["last_updated"].endswith("Z")

    def test_refresh_writes_current_task_when_chain_points_elsewhere(
        self,
        db_with_task,
    ):
        """A re-activation that re-targets a different task within the
        same worktree (rare but supported by single-task-per-chain shape)
        rewrites current_task on the chain row idempotently."""
        self._seed_stale_chain(db_with_task)
        insert_epic_task(
            db_with_task,
            epic_id=TEST_ITEM_ID,
            task_num=2,
            title="Second task",
            status="planned",
        )
        p = _p(db_with_task)
        db_with_task.execute(
            "UPDATE epic_tasks SET dispatch_attempts=1 "
            f"WHERE epic_id={p} AND task_num={p}",
            (str(TEST_ITEM_ID), 2),
        )
        db_with_task.commit()

        epic.dispatch_chain_refresh_for_activation(
            db_with_task,
            str(TEST_ITEM_ID),
            "YOK-42-lane",
            "2",
        )

        row = db_with_task.execute(
            "SELECT c.current_task, c.current_attempt "
            "FROM epic_dispatch_chains c JOIN item_worktrees iw "
            "ON iw.id=c.item_worktree_id "
            f"WHERE c.epic_id={p} AND iw.branch={p}",
            (str(TEST_ITEM_ID), "YOK-42-lane"),
        ).fetchone()
        assert row["current_task"] == "2"
        assert row["current_attempt"] == 1

    def test_refresh_defaults_attempt_to_one_when_dispatch_attempts_unset(
        self,
        db_with_task,
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
            db_with_task,
            str(TEST_ITEM_ID),
            "YOK-42-lane",
            "1",
        )

        row = db_with_task.execute(
            "SELECT c.current_attempt FROM epic_dispatch_chains c "
            "JOIN item_worktrees iw ON iw.id=c.item_worktree_id "
            f"WHERE c.epic_id={p} AND iw.branch={p}",
            (str(TEST_ITEM_ID), "YOK-42-lane"),
        ).fetchone()
        assert row["current_attempt"] == 1

    def test_refresh_raises_when_chain_row_missing(self, db_with_task):
        with pytest.raises(LookupError, match="dispatch chain"):
            epic.dispatch_chain_refresh_for_activation(
                db_with_task,
                str(TEST_ITEM_ID),
                "missing-lane",
                "1",
            )

    def test_refresh_raises_when_task_row_missing(self, db):
        insert_item(
            db,
            id=TEST_ITEM_ID,
            type="epic",
            status="planned",
            project="yoke",
        )
        p = _p(db)
        lane = insert_item_worktree(
            db,
            item_id=TEST_ITEM_ID,
            branch="YOK-42-lane",
            lane_role="worker",
        )
        db.execute(
            """INSERT INTO epic_dispatch_chains
               (epic_id, item_worktree_id, queue, current_index, current_task,
                current_attempt, max_attempts, no_chain, started_at,
                last_updated)
               VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})""".format(p=p),
            (
                TEST_ITEM_ID,
                lane["id"],
                json.dumps(["9"]),
                0,
                "9",
                0,
                5,
                0,
                "",
                "2025-01-01T00:00:00Z",
            ),
        )
        db.commit()
        with pytest.raises(LookupError, match="epic_tasks row"):
            epic.dispatch_chain_refresh_for_activation(
                db,
                str(TEST_ITEM_ID),
                "YOK-42-lane",
                "9",
            )
