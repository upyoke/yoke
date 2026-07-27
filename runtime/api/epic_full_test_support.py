"""Shared item and task fixtures for core epic tests."""

import pytest

from yoke_core.domain import epic
from runtime.api.conftest import insert_item


TEST_EPIC_ID = 42
TEST_EPIC_REF = f"YOK-{TEST_EPIC_ID}"
TEST_EPIC_BRANCH = TEST_EPIC_REF
TEST_EPIC_BRANCH_NEXT = f"{TEST_EPIC_REF}-new"
TEST_EPIC_WORKTREE_PATH = f"/tmp/worktrees/{TEST_EPIC_REF}"


def _p(conn) -> str:
    return epic._placeholder(conn)


def _task_row(conn, epic_id: int, task_num: int):
    return conn.execute(
        f"SELECT * FROM epic_tasks WHERE epic_id={_p(conn)} AND task_num={_p(conn)}",
        (str(epic_id), task_num),
    ).fetchone()


def _task_field(conn, epic_id: int, task_num: int, field: str):
    row = _task_row(conn, epic_id, task_num)
    return row[field] if row else None


def _task_lane_field(conn, epic_id: int, task_num: int, field: str):
    row = conn.execute(
        "SELECT iw.branch, iw.path FROM epic_tasks t "
        "LEFT JOIN item_worktrees iw ON iw.id=t.item_worktree_id "
        f"WHERE t.epic_id={_p(conn)} AND t.task_num={_p(conn)}",
        (str(epic_id), task_num),
    ).fetchone()
    return row[field] if row else None


@pytest.fixture(autouse=True)
def _seed_epic_item(test_db):
    insert_item(
        test_db,
        id=TEST_EPIC_ID,
        type="epic",
        status="planned",
        project="yoke",
    )
