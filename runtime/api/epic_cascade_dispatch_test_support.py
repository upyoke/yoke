"""Database fixtures for epic cascade and dispatch-chain tests."""

import json

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.epic_task_scope import (
    finalize_generated_task_scopes,
    set_no_files_scope,
)
from runtime.api.conftest import insert_item, insert_epic_task
from runtime.api.fixtures.backlog import insert_item_worktree


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
    insert_item(db, id=TEST_ITEM_ID, workflow_id="epic", status="planned", project="yoke")
    insert_epic_task(
        db, epic_id=TEST_ITEM_ID, task_num=1, title="First task", status="planning"
    )
    set_no_files_scope(db, TEST_ITEM_ID, 1)
    finalize_generated_task_scopes(db, TEST_ITEM_ID)
    return db


@pytest.fixture
def db_with_chain(db_with_task):
    """DB with a dispatch chain for testing advance logic."""
    queue = json.dumps([1, 2, 3])
    p = _p(db_with_task)
    lane = insert_item_worktree(
        db_with_task,
        item_id=TEST_ITEM_ID,
        branch=TEST_ITEM_REF,
        lane_role="worker",
    )
    db_with_task.execute(
        """INSERT INTO epic_dispatch_chains
           (epic_id, item_worktree_id, queue, current_index, current_task,
            current_attempt, max_attempts, no_chain, started_at, last_updated)
           VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})""".format(p=p),
        (TEST_ITEM_ID, lane["id"], queue, 0, "1", 1, 5, 0, "", ""),
    )
    db_with_task.commit()
    return db_with_task
