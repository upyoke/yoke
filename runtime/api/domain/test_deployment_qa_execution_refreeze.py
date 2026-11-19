"""A waiting item-QA execution moved by takeover follows the successor's deploy."""

from __future__ import annotations

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import ITEM_QA_STAGE
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
from yoke_core.domain.qa_plan_execution_store import select_plan_execution


def _begin(conn, run_id):
    return begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=takeover.WAITING,
        actor_id="1",
        session_id=takeover.DRIVER_SESSION,
    )


def _queued_then_taken_over(conn, monkeypatch, *, cursor=0):
    """WAITING's item QA waits for a host when NEW takes the release over."""
    takeover._seed_old(conn, run_qa=False)
    execution = _begin(conn, takeover.OLD)
    conn.execute(
        "UPDATE qa_plan_executions SET state='waiting',cursor_ordinal=%s WHERE id=%s",
        (cursor, execution["id"]),
    )
    conn.commit()
    takeover._seed_new(conn)
    takeover._contains(monkeypatch)
    takeover.take_over_waiting_run(
        conn, takeover.NEW, session_id=takeover.DRIVER_SESSION
    )
    return select_plan_execution(conn, execution["id"], lock=False)


def _redeploy_new(conn):
    """NEW deploys its own build to the destination and stands on item QA."""
    from yoke_core.domain.deployment_stage_receipts import (
        allocate_deployment_stage_receipt,
        complete_deployment_stage_receipt,
    )

    conn.execute(
        "UPDATE deployment_runs SET status='executing',current_stage='deploy',"
        "composition_frozen_at=created_at,requirement_snapshot=("
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s) WHERE id=%s",
        (takeover.OLD, takeover.NEW),
    )
    receipt = allocate_deployment_stage_receipt(
        conn,
        run_id=takeover.NEW,
        stage_name="deploy",
        correlation_id=f"{takeover.NEW}-deploy-1",
        target_kind="persistent_environment",
        executor="test",
        commit=False,
    )
    complete_deployment_stage_receipt(
        conn,
        run_id=takeover.NEW,
        receipt_id=int(receipt["id"]),
        correlation_id=str(receipt["correlation_id"]),
        status="ready",
        target_name="stage",
        observed_url="https://preview.example.test",
        observed_release_lineage=takeover.NEW_LINEAGE,
        executor_receipt="test://deploy-ready",
        commit=False,
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
        (ITEM_QA_STAGE, takeover.NEW),
    )
    conn.commit()


def _order(conn, execution_id):
    return conn.execute(
        "SELECT execution_order FROM qa_plan_executions WHERE id=%s", (execution_id,)
    ).fetchone()["execution_order"]


def test_waiting_execution_begins_against_the_successors_deploy(test_db, monkeypatch):
    moved = _queued_then_taken_over(test_db, monkeypatch)
    order = _order(test_db, moved["id"])
    assert moved["deployment_run_id"] == takeover.NEW
    assert moved["execution_target"]["deployment"]["run_id"] == takeover.OLD
    _redeploy_new(test_db)
    # `yoke qa plan run` materializes the successor's stage before it begins.
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=takeover.WAITING,
    )
    begun = _begin(test_db, takeover.NEW)
    assert begun["id"] == moved["id"]
    assert begun["state"] == "active"
    deployment = begun["execution_target"]["deployment"]
    assert deployment["run_id"] == takeover.NEW
    assert deployment["release_lineage"] == takeover.NEW_LINEAGE
    assert deployment["starting_run_id"] == takeover.OLD
    observation = begun["execution_target"]["observation"]
    assert observation["observed_release_lineage"] == takeover.NEW_LINEAGE
    assert begun["execution_target_digest"] != moved["execution_target_digest"]
    assert _order(test_db, moved["id"]) == order


def test_begun_execution_keeps_its_predecessor_target(test_db, monkeypatch):
    from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

    moved = _queued_then_taken_over(test_db, monkeypatch, cursor=1)
    _redeploy_new(test_db)
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=takeover.WAITING,
    )
    # A walk that ran cases is never moved onto another build.
    with pytest.raises(QaPlanExecutionStateError, match="qa_roster_changed"):
        _begin(test_db, takeover.NEW)
    kept = select_plan_execution(test_db, moved["id"], lock=False)
    assert kept["execution_target"]["deployment"]["run_id"] == takeover.OLD
    assert kept["execution_target_digest"] == moved["execution_target_digest"]


def test_owner_re_begin_after_a_stale_refusal_re_targets_in_place(
    test_db, monkeypatch
):
    moved = _queued_then_taken_over(test_db, monkeypatch)
    # The controller's first begin activated it, then refused the stale target.
    test_db.execute(
        "UPDATE qa_plan_executions SET state='active' WHERE id=%s", (moved["id"],)
    )
    test_db.commit()
    _redeploy_new(test_db)
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=takeover.WAITING,
    )
    again = _begin(test_db, takeover.NEW)
    assert again["id"] == moved["id"]
    assert again["execution_target"]["deployment"]["run_id"] == takeover.NEW
