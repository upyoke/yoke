"""A cancelled walk-end releases its host only on proven scratch removal.

A verified same-lease reset to the declared baseline after cancellation is the
restore proof, so walk-end does not restore twice; any other reset receipt
cannot stand in for it.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.domain.agent_mission_qa_test_support import ACTOR, _request
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.qa_aborted_mission_review_test_support import _recorded_mission
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import machine_qa_mission_walk
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.machine_reset_debt import reset_owed
from yoke_core.domain.qa_plan_execution_abort_state import abort_request
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution
from yoke_core.domain.qa_plan_execution_stop import stop_plan_execution
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain.qa_plan_review import begin_plan_review

ITEM = 4595


def _cancelled_walk(test_db: Any, tmp_path: Any, monkeypatch: Any):
    requirement_id, execution_id, run_id = _recorded_mission(
        test_db, tmp_path, monkeypatch, ITEM
    )
    begin_plan_review(test_db, lock_plan_execution(test_db, execution_id))
    test_db.commit()
    execution = lock_plan_execution(test_db, execution_id)
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
    return requirement_id, execution, run_id


def _record_reset(test_db: Any, execution: dict, change: str | None) -> None:
    """Record a reset receipt on the walk's lease, valid unless *change* says."""
    from yoke_core.domain.host_control_runner import load_test_machine_contract
    from yoke_core.domain.machine_operation_recording import (
        record_test_machine_operation,
    )
    from yoke_core.domain.machine_qa_execution_protocol import _issue

    baseline = execution["roster"][0]["host_baseline"]
    lease = get_claim(test_db, execution["test_machine_lease_id"])
    candidate = load_test_machine_contract(
        test_db, project="yoke", test_machine=lease.target.test_machine
    )
    reset_to = "shell-preconfigured" if change == "wrong_baseline" else baseline
    contract = _issue(
        test_db, candidate, lease, operation="reset", checks=(),
        baselines=[reset_to], cases=(),
    )
    record_test_machine_operation(
        test_db,
        test_machine=lease.target.test_machine,
        operation="reset",
        status="error" if change == "failed" else "verified",
        checks=[{"name": reset_to, "ok": change != "failed"}],
        error_code="reset_failed" if change == "failed" else None,
        lease_id=lease.id + 1 if change == "foreign_lease" else lease.id,
        contract_digest=contract.contract_digest,
    )
    if change == "stale":
        test_db.execute(
            "UPDATE test_machine_operation_receipts SET performed_at=%s",
            (utc_now() - timedelta(days=1),),
        )
    test_db.commit()


def _access(execution: dict, requirement_id: int, **payload: Any):
    return handle_agent_mission_access(
        _request(
            "test_machine.mission.access",
            item_id=ITEM,
            execution_id=str(execution["id"]),
            requirement_id=requirement_id,
            payload=payload,
        )
    )


def _host(monkeypatch: Any, restores: list[str]) -> None:
    def reach(name: str):
        restores.append(name)
        return SimpleNamespace(ok=True, error_code=None, evidence={})

    monkeypatch.setattr(
        machine_qa_mission_walk,
        "_execution",
        lambda _contract: SimpleNamespace(
            control=FakeHostControl(),
            material=SimpleNamespace(secrets={}),
            reach_baseline=reach,
        ),
    )


def test_valid_reset_settles_walk_end_without_a_second_restore(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    requirement_id, execution, run_id = _cancelled_walk(test_db, tmp_path, monkeypatch)
    lease_id = execution["test_machine_lease_id"]
    machine = get_claim(test_db, lease_id).target.test_machine
    _record_reset(test_db, execution, None)
    begun = _access(execution, requirement_id, cleanup="begin", run_id=run_id)
    assert begun.primary_success, begun.error
    assert begun.result_payload["restore_proven"] is True
    restores: list[str] = []
    _host(monkeypatch, restores)
    ended = machine_qa_mission_walk.execute_agent_mission_walk_end(
        begun.result_payload["execution"], restore_proven=True
    )
    assert ended["removed"] and ended["starting_state_restore"] is None
    assert restores == []
    finished = _access(
        execution, requirement_id, cleanup="finish", run_id=run_id,
        lease_id=lease_id, restore=None,
    )
    assert finished.primary_success, finished.error
    assert not get_claim(test_db, lease_id).is_active
    assert reset_owed(test_db, machine) is None
    settled = lock_plan_execution(test_db, str(execution["id"]))
    test_db.rollback()
    assert settled["state"] == "aborted"


@pytest.mark.parametrize(
    "change", ["absent", "stale", "failed", "wrong_baseline", "foreign_lease"]
)
def test_unproven_reset_keeps_custody_and_restores_as_before(
    test_db: Any, tmp_path: Any, monkeypatch: Any, change: str
) -> None:
    requirement_id, execution, run_id = _cancelled_walk(test_db, tmp_path, monkeypatch)
    lease_id = execution["test_machine_lease_id"]
    if change != "absent":
        _record_reset(test_db, execution, change)
    begun = _access(execution, requirement_id, cleanup="begin", run_id=run_id)
    assert begun.primary_success, begun.error
    assert begun.result_payload["restore_proven"] is False
    restores: list[str] = []
    _host(monkeypatch, restores)
    ended = machine_qa_mission_walk.execute_agent_mission_walk_end(
        begun.result_payload["execution"], restore_proven=False
    )
    assert restores == [execution["roster"][0]["host_baseline"]]
    assert ended["starting_state_restore"]["restored"]
    # A restore-less finish cannot borrow an unproven reset: custody stays.
    refused = _access(
        execution, requirement_id, cleanup="finish", run_id=run_id,
        lease_id=lease_id, restore=None,
    )
    assert not refused.primary_success
    assert "mission_cleanup_restore_unproven" in refused.error.message
    assert get_claim(test_db, lease_id).is_active
    current = lock_plan_execution(test_db, str(execution["id"]))
    test_db.rollback()
    assert current["state"] == "walking"
