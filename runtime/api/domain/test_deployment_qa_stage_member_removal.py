"""A live item QA dispatch survives audited membership removal."""

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain import deployment_qa_stage_gate as gate
from yoke_core.domain import deployment_qa_stage_materialization as materialization
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_member_removal import remove_member_on
from yoke_core.domain.deployment_run_membership_removals import (
    record_membership_removal,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

RUN = "run-live-member-removal"
REMOVED = 9761
REMAINING = 9762


def _ready_run(conn):
    stages = _stages(_plan(conn))
    _seed_run(conn, run_id=RUN, stages=stages, members=(REMOVED, REMAINING))
    for member in (REMOVED, REMAINING):
        conn.execute("UPDATE items SET status='release' WHERE id=%s", (member,))
    materialization.materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=REMAINING,
    )
    execution = begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=REMAINING,
        actor_id="2",
        session_id="remaining-member-qa",
    )
    _complete_case(conn, execution)
    conn.commit()
    return stages[-1]


@pytest.mark.parametrize("boundary", ["materialize", "gate"])
def test_removed_member_does_not_fail_live_stage(test_db, monkeypatch, boundary):
    stage = _ready_run(test_db)
    module = materialization if boundary == "materialize" else gate
    name = (
        "materialize_deployment_qa_stage"
        if boundary == "materialize"
        else "deployment_qa_stage_status"
    )
    original = getattr(module, name)
    visited = []

    def remove_during_dispatch(conn, **kwargs):
        member = kwargs.get("deployment_member_item_id", kwargs.get("member_item_id"))
        visited.append(member)
        if member == REMOVED:
            remove_member_on(conn, RUN, member, reason="member awaits next release")
            conn.commit()
        return original(conn, **kwargs)

    monkeypatch.setattr(module, name, remove_during_dispatch)
    assert materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=RUN) == (
        0,
        "",
    )
    assert visited == ([REMOVED] if boundary == "materialize" else [REMOVED, REMAINING])
    assert (
        test_db.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (RUN,)
        ).fetchone()["item_id"]
        == REMAINING
    )
    assert gate.deployment_qa_stage_status(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=REMAINING
    )["accepted"]


def test_unrecorded_missing_member_still_fails_live_stage(test_db, monkeypatch):
    stage = _ready_run(test_db)
    original = materialization.materialize_deployment_qa_stage

    def disappear(conn, **kwargs):
        conn.execute(
            "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
            (RUN, REMOVED),
        )
        conn.commit()
        return original(conn, **kwargs)

    monkeypatch.setattr(materialization, "materialize_deployment_qa_stage", disappear)
    code, reason = materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=RUN)
    assert code == 1
    assert "not an attached member" in reason


def test_never_attached_member_still_refuses_with_removal_history(test_db):
    _ready_run(test_db)
    remove_member_on(test_db, RUN, REMOVED, reason="member awaits next release")
    test_db.commit()
    with pytest.raises(ValueError, match="not an attached member"):
        materialization.materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member_item_id=REMOVED + 10,
        )


def test_recorded_removal_does_not_hide_attached_member_defect(test_db, monkeypatch):
    stage = _ready_run(test_db)
    record_membership_removal(
        test_db, RUN, REMOVED, reason="stale removal", session_id=None, actor_id=2
    )
    test_db.commit()

    def refuse(*args, **kwargs):
        raise ValueError("invalid pinned QA plan; repair the plan")

    monkeypatch.setattr(materialization, "materialize_deployment_qa_stage", refuse)
    assert materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=RUN) == (
        1,
        "invalid pinned QA plan; repair the plan",
    )
