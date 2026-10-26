"""A lane several tasks of one epic shared is pruned once the epic closes.

No single task owns such a lane, so the prune verdict waits for the epic:
every task finished and the epic itself done or cancelled. One unfinished
task, or an epic still open, keeps the lane.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_epic_task,
    insert_item,
    insert_item_worktree,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import merge_engine_internal_ops as ops

EPIC_ID = 9601
BRANCH = "YOK-9601-shared"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _shared_lane(db: str, *, epic_status: str, task_statuses: tuple[str, ...]):
    conn = connect_test_db(db)
    try:
        insert_item(
            conn,
            id=EPIC_ID,
            workflow_id="epic",
            status=epic_status,
            source=str(seed_human_actor(conn)),
        )
        lane = insert_item_worktree(
            conn, item_id=EPIC_ID, branch=BRANCH, lane_role="worker"
        )
        for task_num, status in enumerate(task_statuses, start=1):
            insert_epic_task(
                conn,
                epic_id=EPIC_ID,
                task_num=task_num,
                status=status,
                item_worktree_id=int(lane["id"]),
            )
        conn.commit()
    finally:
        conn.close()


def _verdict() -> dict:
    outcome = ops.handle_prune_authority_verdict(
        FunctionCallRequest(
            function="merge.prune.authority_verdict",
            actor=ActorContext(actor_id=None, session_id="s-finished-epic"),
            target=TargetRef(kind="global"),
            payload={"branch": BRANCH},
        )
    )
    assert outcome.primary_success, outcome.error
    return outcome.result_payload


@pytest.mark.parametrize("epic_status", ["done", "cancelled"])
def test_a_finished_epic_owns_the_lane_its_tasks_shared(db, epic_status):
    _shared_lane(db, epic_status=epic_status, task_statuses=("done", "done"))

    verdict = _verdict()

    if epic_status == "cancelled":
        assert verdict["prunable"] is True
        assert verdict["cancelled_item_ref"]
        return
    assert verdict == {
        "prunable": True,
        "reason": "prunable",
        "item_ref": verdict["item_ref"],
    }
    assert verdict["item_ref"].endswith(str(EPIC_ID))


def test_an_epic_with_an_unfinished_task_keeps_the_lane(db):
    _shared_lane(db, epic_status="done", task_statuses=("done", "implementing"))

    assert _verdict() == {"prunable": False, "reason": "no_terminal_owner"}


def test_an_open_epic_keeps_the_lane_its_finished_tasks_shared(db):
    _shared_lane(db, epic_status="implementing", task_statuses=("done", "done"))

    assert _verdict() == {"prunable": False, "reason": "no_terminal_owner"}
