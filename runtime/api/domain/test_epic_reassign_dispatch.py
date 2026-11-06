"""Task reassignment preserves dispatch ownership and activation."""

import json

import pytest

from runtime.api.domain.test_epic_amend import _add_row, _finalize_rows
from yoke_core.domain.epic_amend import task_reassign
from yoke_core.domain.epic_task_crud import task_upsert
from yoke_core.domain.epic_dispatch import (
    dispatch_chain_refresh_for_activation,
    dispatch_chain_upsert,
)


def _chains(conn):
    rows = conn.execute(
        "SELECT iw.branch, c.queue, c.current_index, c.current_task "
        "FROM epic_dispatch_chains c JOIN item_worktrees iw ON iw.id=c.item_worktree_id"
    ).fetchall()
    return {r["branch"]: dict(r) for r in rows}


@pytest.mark.parametrize("existing_destination", [False, True])
def test_reassign_moves_queue_and_allows_activation(test_db, existing_destination):
    item_id = 100
    _add_row(test_db, item_id, 1, "first", worktree="old", status="planned")
    task_upsert(test_db, str(item_id), 2, "second", worktree="old")
    _add_row(test_db, item_id, 3, "third", worktree="new", status="planned")
    _finalize_rows(test_db, item_id, 1, 2, 3)
    dispatch_chain_upsert(
        test_db, str(item_id), "old", {"queue": ["1", "2"], "current_index": 1}
    )
    if existing_destination:
        dispatch_chain_upsert(test_db, str(item_id), "new", {"queue": ["3"]})
    task_reassign(test_db, item_id, 1, "new")
    chains = _chains(test_db)
    assert json.loads(chains["old"]["queue"]) == ["2"]
    assert chains["old"]["current_index"] == 0
    assert json.loads(chains["new"]["queue"]) == (
        ["3", "1"] if existing_destination else ["1"]
    )
    dispatch_chain_refresh_for_activation(test_db, str(item_id), "new", "1")
    assert _chains(test_db)["new"]["current_task"] == "1"


def test_reassign_in_flight_refuses_without_creating_lane(test_db):
    item_id = 100
    _add_row(test_db, item_id, 1, "first", worktree="old", status="implementing")
    _finalize_rows(test_db, item_id, 1)
    dispatch_chain_upsert(
        test_db, str(item_id), "old", {"queue": ["1"], "current_task": "1"}
    )
    before = _chains(test_db)
    with pytest.raises(ValueError, match="task_reassign_in_flight:.*Finish or halt"):
        task_reassign(test_db, item_id, 1, "new")
    assert _chains(test_db) == before
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM item_worktrees WHERE branch='new'"
        ).fetchone()[0]
        == 0
    )
    row = test_db.execute(
        "SELECT iw.branch FROM epic_tasks t JOIN item_worktrees iw ON iw.id=t.item_worktree_id "
        "WHERE t.epic_id=%s AND t.task_num=1",
        (str(item_id),),
    ).fetchone()
    assert row["branch"] == "old"


def test_reassign_rolls_back_queue_lane_and_task_on_write_failure(test_db, monkeypatch):
    from yoke_core.domain import item_activity

    item_id = 100
    _add_row(test_db, item_id, 1, "first", worktree="old", status="planned")
    _finalize_rows(test_db, item_id, 1)
    dispatch_chain_upsert(test_db, str(item_id), "old", {"queue": ["1"]})
    before = _chains(test_db)

    def fail(**kwargs):
        raise RuntimeError("write failed")

    monkeypatch.setattr(
        item_activity, "touch_item_activity", lambda *a, **kw: fail(**kw)
    )
    with pytest.raises(RuntimeError, match="write failed"):
        task_reassign(test_db, item_id, 1, "new")
    assert _chains(test_db) == before
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM item_worktrees WHERE branch='new'"
        ).fetchone()[0]
        == 0
    )
