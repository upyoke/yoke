"""A cancelled mission walk can reset its declared baseline on its retained lease."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.agent_mission_qa_test_support import ACTOR
from runtime.api.domain.qa_abort_reset_test_support import operation
from runtime.api.domain.qa_aborted_mission_review_test_support import _recorded_mission
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_core.domain.qa_plan_execution_abort_state import (
    abort_request,
    mission_walk_owed,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution
from yoke_core.domain.qa_plan_execution_stop import stop_plan_execution
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain.qa_plan_review import begin_plan_review

ITEM = 4594


def _walking(test_db: Any, tmp_path: Any, monkeypatch: Any, *, cancel: bool):
    _requirement_id, execution_id, _run_id = _recorded_mission(
        test_db, tmp_path, monkeypatch, ITEM
    )
    begin_plan_review(test_db, lock_plan_execution(test_db, execution_id))
    test_db.commit()
    execution = lock_plan_execution(test_db, execution_id)
    assert execution["state"] == "walking"
    if cancel:
        with pytest.raises(QaPlanExecutionStateError, match="qa_abort_walk_end_required"):
            stop_plan_execution(
                test_db,
                execution,
                actor_id=ACTOR.actor_id,
                session_id=ACTOR.session_id,
                reason="owner stop",
            )
        test_db.rollback()
        execution = lock_plan_execution(test_db, execution_id)
        test_db.rollback()
        assert abort_request(execution)
    baseline = execution["roster"][0]["host_baseline"]
    assert baseline
    return execution, baseline


def test_cancelled_walk_owner_resets_baseline_and_keeps_custody(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    execution, baseline = _walking(test_db, tmp_path, monkeypatch, cancel=True)
    lease_id = execution["test_machine_lease_id"]
    begun = handle_operation_begin(operation(ACTOR, baseline=baseline))
    assert begun.primary_success, begun.error
    issued = begun.result_payload["execution"]
    assert issued["lease_id"] == lease_id
    submitted = handle_operation_submit(
        operation(
            ACTOR,
            baseline=baseline,
            lease_id=lease_id,
            contract_digest=issued["contract_digest"],
            status="verified",
            checks=[{"name": baseline, "ok": True}],
        )
    )
    assert submitted.primary_success, submitted.error
    assert get_claim(test_db, lease_id).is_active
    current = lock_plan_execution(test_db, str(execution["id"]))
    assert current["state"] == "walking"
    assert abort_request(current)["reason"] == "owner stop"
    # The reset is not the handback: walk-end still owes its own restore proof.
    assert mission_walk_owed(test_db, current)
    with pytest.raises(QaPlanExecutionStateError):
        finish_plan_execution(test_db, current, state="aborted", reason="reset only")
    test_db.rollback()
    assert get_claim(test_db, lease_id).is_active


@pytest.mark.parametrize("op,wrong", [("verify", False), ("reset", True)])
def test_cancelled_walk_refuses_other_operations(
    test_db: Any, tmp_path: Any, monkeypatch: Any, op: str, wrong: bool
) -> None:
    _execution, baseline = _walking(test_db, tmp_path, monkeypatch, cancel=True)
    refused = handle_operation_begin(
        operation(ACTOR, op, baseline="shell-preconfigured" if wrong else baseline)
    )
    assert not refused.primary_success
    assert "qa_abort_reset_required" in refused.error.message


def test_cancelled_walk_refuses_unrelated_caller(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    _execution, baseline = _walking(test_db, tmp_path, monkeypatch, cancel=True)
    monkeypatch.setattr(
        "yoke_core.domain.session_steering_authority.covering_session_seat",
        lambda *a, **kw: None,
    )
    refused = handle_operation_begin(
        operation(ActorContext(actor_id="1", session_id="foreign"), baseline=baseline)
    )
    assert not refused.primary_success
    assert "qa_abort_reset_authority_required" in refused.error.message


def test_ordinary_walk_still_refuses_baseline_reset(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    execution, baseline = _walking(test_db, tmp_path, monkeypatch, cancel=False)
    refused = handle_operation_begin(operation(ACTOR, baseline=baseline))
    assert not refused.primary_success
    assert "test_machine_cleanup_live_lease" in refused.error.message
    assert get_claim(test_db, execution["test_machine_lease_id"]).is_active
