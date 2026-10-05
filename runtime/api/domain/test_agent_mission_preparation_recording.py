"""Preparation failures persist their cause and baseline proof without a walker."""

import json

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    configure_test_machine,
)
from runtime.api.domain.test_agent_mission_qa import (
    ACTOR,
    _materialize_mission,
    _request,
)
from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review


def test_failed_preparation_persists_qa_error_and_successful_baseline_receipt(
    test_db, tmp_path, monkeypatch
):
    from yoke_core.domain import qa_events

    emitted = []
    monkeypatch.setattr(
        qa_events, "emit_qa_run_event", lambda *a, **kw: emitted.append(kw)
    )
    item_id = 4821
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    execution_id = str(execution["id"])
    begun = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
        )
    )
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    receipt = {
        "baseline": "fresh-host",
        "ok": True,
        "error_code": None,
        "evidence": {"restore_proved": True},
    }
    preparation = {
        "baseline": "fresh-host",
        "ok": False,
        "error_code": "os_package_fixture_failed",
        "scratch_path": "/tmp/planned-scratch",
        "evidence": {
            "baseline_outcome": {
                "name": "fresh-host",
                "state": "completed",
                "receipt": receipt,
            },
            "scratch_created": False,
            "preparation_failure": {
                "phase": "os_packages",
                "diagnostic": "PermissionError: journal is read-only",
                "recovery": "Reconcile the package journal before retrying.",
            },
        },
    }
    ready = handle_agent_mission_ready(
        _request(
            "test_machine.mission.ready",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
            payload={
                "lease_id": contract["lease_id"],
                "contract_digest": contract["contract_digest"],
                "preparation": preparation,
            },
        )
    )
    assert ready.primary_success, ready.error
    result = ready.result_payload["result"]
    assert result["verdict"] == "error"
    assert emitted[-1]["event_name"] == "QARunCaptured"
    assert emitted[-1]["verdict"] == "error"
    assert emitted[-1]["verdict_reason"] == result["error"]
    assert result["case_outcome"] == "blocked_on_precondition"
    assert result["preparation"] == preparation
    row = test_db.execute(
        "SELECT verdict,case_outcome,execution_status,verdict_reason,raw_result FROM qa_runs WHERE id=%s",
        (result["run_id"],),
    ).fetchone()
    assert row["verdict"] == "error"
    assert row["case_outcome"] == "blocked_on_precondition"
    assert row["execution_status"] == "capture_failed"
    assert row["verdict_reason"] == "PermissionError: journal is read-only"
    assert json.loads(row["raw_result"])["preparation"] == preparation
    recorded = test_db.execute(
        "SELECT status,receipt_json FROM test_machine_operation_receipts WHERE lease_id=%s AND operation='reset'",
        (contract["lease_id"],),
    ).fetchone()
    assert recorded["status"] == "verified"
    assert json.loads(recorded["receipt_json"])["checks"][0]["restore_proved"] is True
    current = lock_plan_execution(test_db, execution_id)
    review = begin_plan_review(test_db, current)
    assert review is None
