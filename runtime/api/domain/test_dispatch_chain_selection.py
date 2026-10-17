"""A lane dispatches its first dependency-ready task, not only its queue head."""

from __future__ import annotations

import io

import pytest

from runtime.api.conftest import insert_epic_task, insert_item
from runtime.api.epic_task_sync_orchestrator_test_support import (
    db as db,
    declare_no_file_tasks,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import epic
from yoke_core.domain.dispatch_chain_selection import (
    ChainSelectionRefusal,
    LaneTask,
    dependency_depths,
    select_next_task,
)
from yoke_core.domain.epic_task_sync_local import prepare_dispatch_chains
from yoke_core.domain.handlers.workflow_item_epic_dispatch_advance import (
    handle_dispatch_chain_advance,
)
from yoke_core.domain.item_worktrees import record_worker_item_worktree


def _tasks(*rows):
    return {num: LaneTask(num, status, tuple(deps)) for num, status, deps in rows}


def test_blocked_head_yields_to_ready_later_task():
    # Lane queue [2, 8]: task 2 waits on task 1 in another lane; task 8 is free.
    tasks = _tasks(
        (1, "implementing", ()),
        (2, "planned", (1,)),
        (8, "planned", ()),
    )
    assert select_next_task(["002", "008"], tasks, "scope") == (1, 8)


def test_waiting_task_is_picked_up_once_its_dependency_completes():
    tasks = _tasks(
        (1, "reviewed-implementation", ()),
        (2, "planned", (1,)),
        (8, "done", ()),
    )
    assert select_next_task(["002", "008"], tasks, "scope") == (0, 2)


def test_lane_with_running_task_is_busy():
    tasks = _tasks((2, "implementing", ()), (8, "planned", ()))
    with pytest.raises(ChainSelectionRefusal) as refusal:
        select_next_task(["2", "8"], tasks, "scope")
    assert refusal.value.code == "chain_busy"
    assert "task 2" in refusal.value.message


def test_lane_without_ready_task_names_each_wait():
    tasks = _tasks(
        (1, "planned", ()),
        (2, "planned", (1,)),
        (3, "blocked", ()),
    )
    with pytest.raises(ChainSelectionRefusal) as refusal:
        select_next_task(["2", "3"], tasks, "consumer")
    assert refusal.value.code == "chain_waiting"
    assert "task 2 waits on task(s) 1" in refusal.value.message
    assert "task 3 is blocked" in refusal.value.message
    assert refusal.value.recovery


def test_completed_lane_reports_end_of_queue():
    tasks = _tasks((1, "done", ()), (2, "reviewed-implementation", ()))
    with pytest.raises(ChainSelectionRefusal) as refusal:
        select_next_task(["1", "2"], tasks, "scope")
    assert refusal.value.code == "chain_complete"


def test_queue_naming_a_missing_task_is_refused():
    with pytest.raises(ChainSelectionRefusal) as refusal:
        select_next_task(["5"], _tasks((1, "planned", ())), "scope")
    assert refusal.value.code == "chain_queue_inconsistent"


def test_dependency_depths_refuse_cycles_and_unknown_tasks():
    assert dependency_depths({1: (), 2: (1,), 8: ()}) == {1: 0, 2: 1, 8: 0}
    with pytest.raises(ValueError, match="task_dependency_cycle"):
        dependency_depths({1: (2,), 2: (1,)})
    with pytest.raises(ValueError, match="task_dependency_unknown"):
        dependency_depths({1: (9,)})


def _seed_lane_with_blocked_head(db):
    insert_item(db, id=10, workflow_id="epic", status="planned", project="yoke")
    for number, branch, deps in [
        (1, "worker-a", ""),
        (2, "worker-b", "1"),
        (8, "worker-b", ""),
    ]:
        insert_epic_task(
            db,
            epic_id=10,
            task_num=number,
            title=f"Task {number}",
            status="planned",
            item_worktree_id=record_worker_item_worktree(
                db, item_id=10, branch=branch, path=None
            )["id"],
            dependencies=deps,
        )
    declare_no_file_tasks(db, 10)
    db.commit()


def test_sync_orders_lane_queue_dependencies_first_and_advance_skips_waits(db):
    _seed_lane_with_blocked_head(db)
    out, err = io.StringIO(), io.StringIO()
    assert prepare_dispatch_chains(db, epic_name="10", stdout=out, stderr=err)
    queue = db.execute(
        "SELECT c.queue FROM epic_dispatch_chains c JOIN item_worktrees iw "
        "ON iw.id=c.item_worktree_id WHERE c.epic_id=10 AND iw.branch='worker-b'"
    ).fetchone()["queue"]
    assert queue == '["008", "002"]'

    db.execute("UPDATE epic_tasks SET status='implementing' WHERE task_num=1")
    db.commit()
    assert epic.dispatch_chain_advance(db, "10", "worker-b") == "0|008"


def test_sync_refuses_a_dependency_cycle_with_its_recovery(db):
    _seed_lane_with_blocked_head(db)
    db.execute("UPDATE epic_tasks SET dependencies='2' WHERE task_num=1")
    db.commit()
    out, err = io.StringIO(), io.StringIO()
    assert not prepare_dispatch_chains(db, epic_name="10", stdout=out, stderr=err)
    assert "task_dependency_cycle" in err.getvalue()
    assert "retry yoke items github-sync" in err.getvalue()


def test_advance_handler_returns_named_refusal_code(db, monkeypatch):
    _seed_lane_with_blocked_head(db)
    assert prepare_dispatch_chains(
        db, epic_name="10", stdout=io.StringIO(), stderr=io.StringIO()
    )
    db.execute("UPDATE epic_tasks SET status='implementing' WHERE task_num=8")
    db.commit()

    from contextlib import contextmanager

    from yoke_core.domain import db_helpers

    @contextmanager
    def _connect():
        yield db

    monkeypatch.setattr(db_helpers, "connect", _connect)
    request = FunctionCallRequest(
        function="workflow_item.epic_dispatch_chain.advance",
        actor=ActorContext(session_id="caller"),
        target=TargetRef(kind="epic_task", epic_id=10),
        payload={"worktree": "worker-b"},
    )
    outcome = handle_dispatch_chain_advance(request)
    assert outcome.primary_success is False
    assert outcome.error.code == "chain_busy"
    assert outcome.error.recovery_hint
