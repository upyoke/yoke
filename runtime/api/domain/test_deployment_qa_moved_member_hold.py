"""A moved member waits for the successor's item QA instead of acting early."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import patch

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _claim,
    _project,
    seed_session,
)
from runtime.api.domain.test_deployment_run_target_takeover import (
    NEW,
    OLD,
    PASSED,
    WAITING,
    _contains,
    _seed_new,
    _seed_old,
    _take_over,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deployment_qa_takeover_notice import notify_moved_member_qa
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)
from yoke_core.domain.handlers.qa_plan_materialize import handle_materialize
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.work_claim_targets import make_item_target

_STAGE = [{"name": "item-qa", "step_runner": "qa", "scope": "item"}]


def _item_call():
    return FunctionCallRequest(
        function="qa.plan.materialize",
        actor=ActorContext(actor_id="1", session_id="member-qa"),
        target=TargetRef(kind="item", item_id=WAITING),
        payload={"deployment_stage": "item-qa", "project": "yoke"},
    )


def _materialize(conn):
    with patch(
        "yoke_core.domain.db_helpers.connect", return_value=nullcontext(conn)
    ):
        return handle_materialize(_item_call())


def _freeze_successor(conn) -> None:
    conn.execute(
        "UPDATE deployment_runs SET status='executing', current_stage='deploy', "
        "composition_frozen_at=(SELECT composition_frozen_at FROM deployment_runs "
        "WHERE id=%s), requirement_snapshot=(SELECT requirement_snapshot FROM "
        "deployment_runs WHERE id=%s) WHERE id=%s",
        (OLD, OLD, NEW),
    )
    receipt = allocate_deployment_stage_receipt(
        conn,
        run_id=NEW,
        stage_name="deploy",
        correlation_id="successor-deploy-hold",
        target_kind="persistent_environment",
        executor="test",
        commit=False,
    )
    complete_deployment_stage_receipt(
        conn,
        run_id=NEW,
        receipt_id=int(receipt["id"]),
        correlation_id=str(receipt["correlation_id"]),
        status="ready",
        target_name="stage",
        observed_url="https://preview.example.test",
        observed_release_lineage="c" * 40,
        executor_receipt="test://successor-ready",
        commit=False,
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage='item-qa' WHERE id=%s", (NEW,)
    )
    conn.commit()


def test_item_call_waits_until_the_successor_reaches_item_qa(test_db, monkeypatch):
    _seed_old(test_db, run_qa=False)
    _seed_new(test_db)
    _contains(monkeypatch)
    assert _take_over(test_db) == OLD

    refused = _materialize(test_db)
    assert refused.primary_success is False
    message = refused.error.message
    assert refused.error.code == "qa_subject_unavailable"
    assert f"deployment run {NEW} is 'created'" in message
    assert "item QA opens at item-qa; you will be woken" in message

    _freeze_successor(test_db)
    proceeded = _materialize(test_db)
    assert proceeded.primary_success, proceeded.error
    assert "you will be woken" not in str(proceeded.result_payload)


def test_takeover_tells_each_moved_owner_once(test_db, monkeypatch):
    _seed_old(test_db, run_qa=False)
    _project(test_db)
    for session_id, item_id in ((HOLDER_A, PASSED), (HOLDER_B, WAITING)):
        seed_session(test_db, session_id)
        _claim(
            test_db,
            session_id=session_id,
            target_kind="item",
            scope_json=make_item_target(item_id).scope_json(),
        )
    _seed_new(test_db)
    _contains(monkeypatch)
    assert _take_over(test_db) == OLD
    notify_moved_member_qa(
        test_db,
        old_id=OLD,
        new_id=NEW,
        item_ids=(PASSED, WAITING),
        stages=_STAGE,
    )
    test_db.commit()

    for item_id in (PASSED, WAITING):
        [body] = _bodies(test_db, f"deployment-qa-moved:{NEW}:{item_id}")
        assert render_item_ref(test_db, item_id) in body
        assert f"to run {NEW}" in body
        assert "item QA stage 'item-qa'" in body
        assert "do not act on the predecessor's wake" in body
