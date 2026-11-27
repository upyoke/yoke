"""An abort during pre-walk mission preparation keeps custody until restore settles.

Feedback 98859: an owner abort during a live ``mission_baseline`` heartbeat
terminalized the execution and left the lab to a 120-second hold-over while
the blocking baseline call still ran. These tests drive the registered
admission, heartbeat, abort and ``mission.ready`` paths.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
from yoke_contracts.timestamps import utc_now

from runtime.api.domain.agent_mission_qa_test_support import (
    ACTOR,
    _materialize_mission,
    _request,
)
from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_qa_session_seed import seed_registered_qa_launch
from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.handlers.qa_plan_execution import (
    handle_plan_execution_abort,
    handle_plan_execution_heartbeat,
)
from yoke_core.domain.qa_host_holdover import HOLDOVER_TTL, expire_holdover
from yoke_core.domain.qa_plan_execution_abort_state import abort_request
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)

ITEM = 4763
OTHER_ITEM = 4764
RESTORED = {"baseline": "fresh-host", "ok": True, "error_code": None, "evidence": {}}


def _call(handler: Any, function: str, execution_id: str, item_id: int = ITEM, **payload):
    return handler(
        FunctionCallRequest(
            function=function,
            actor=ACTOR,
            target=TargetRef(kind="item", item_id=item_id),
            payload={"execution_id": execution_id, **payload},
        )
    )


def _admit(test_db: Any, item_id: int) -> tuple[str, int, Any]:
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    begun = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=str(execution["id"]),
            ordinal=0,
            requirement_id=requirement_id,
        )
    )
    assert begun.primary_success, begun.error
    return str(execution["id"]), requirement_id, begun.result_payload


def _setup(test_db: Any, tmp_path: Any, monkeypatch: Any):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_registered_qa_launch(test_db, ACTOR.session_id, actor_id=int(ACTOR.actor_id))
    execution_id, requirement_id, begun = _admit(test_db, ITEM)
    assert begun["state"] == "ready"
    return execution_id, requirement_id, begun["execution"]


def _abort(execution_id: str):
    return _call(
        handle_plan_execution_abort,
        "qa.plan_execution.abort",
        execution_id,
        reason="owner stopped the run",
    )


def _ready(execution_id: str, requirement_id: int, contract: dict, restore: dict):
    preparation = {
        "baseline": "fresh-host",
        "ok": False,
        "error_code": "qa_host_abort_requested",
        "scratch_path": "/tmp/planned-scratch",
        "evidence": {
            "baseline_outcome": {"name": "fresh-host", "state": "completed", "receipt": RESTORED},
            "scratch_created": False,
            "abort": {"reason": "qa_host_abort_requested", "host_work_stopped": True},
            "preparation_failure": {
                "phase": "preparation_heartbeat",
                "error_code": "qa_host_abort_requested",
                "diagnostic": "qa_host_abort_requested: stop host actions",
                "recovery": "Keep the runner connected through cleanup.",
            },
            "starting_state_restore": restore,
        },
    }
    return handle_agent_mission_ready(
        _request(
            "test_machine.mission.ready",
            item_id=ITEM,
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


def _current(test_db: Any, execution_id: str) -> dict:
    current = lock_plan_execution(test_db, execution_id)
    test_db.rollback()
    return current


def test_abort_during_baseline_keeps_custody_until_the_docket_restore(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    execution_id, requirement_id, contract = _setup(test_db, tmp_path, monkeypatch)
    lease_id = int(contract["lease_id"])
    beat = _call(handle_plan_execution_heartbeat, "qa.plan_execution.heartbeat", execution_id)
    assert beat.primary_success, beat.error
    assert beat.result_payload["abort_requested"] is False

    aborted = _abort(execution_id)
    assert not aborted.primary_success
    assert "qa_abort_restore_pending" in aborted.error.message
    current = _current(test_db, execution_id)
    assert current["state"] == "active"
    assert current["test_machine_lease_id"] == lease_id
    assert abort_request(current)["reason"] == "owner stopped the run"

    # Custody is the execution's own lease, not a hold-over that can lapse.
    claim = get_claim(test_db, lease_id)
    later = utc_now() + HOLDOVER_TTL + timedelta(seconds=30)
    assert not expire_holdover(test_db, claim, now=later)
    test_db.commit()
    assert get_claim(test_db, lease_id).is_active

    # A second admission of the same lab, even by the same session, waits.
    woken: list[str] = []
    monkeypatch.setattr(
        "yoke_core.domain.session_message_service.send_message",
        lambda _conn, **kwargs: woken.append(kwargs["body"]) or {"message_id": "m"},
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_explicit_wake.mark_explicit_stopped_wake",
        lambda *a, **k: None,
    )
    other_id, _other_requirement, other = _admit(test_db, OTHER_ITEM)
    assert other["state"] == "waiting", other
    assert get_claim(test_db, lease_id).is_active

    # The runner's heartbeat carries the cancellation while it finishes.
    beat = _call(handle_plan_execution_heartbeat, "qa.plan_execution.heartbeat", execution_id)
    assert beat.primary_success, beat.error
    assert beat.result_payload["abort_requested"] is True

    ready = _ready(execution_id, requirement_id, contract, {"restored": True, **RESTORED})
    assert ready.primary_success, ready.error
    settled = _current(test_db, execution_id)
    assert settled["state"] == "aborted"
    assert settled["release_reason"].endswith("owner stopped the run")
    assert settled["test_machine_lease_id"] is None
    assert not get_claim(test_db, lease_id).is_active
    # The matching cleanup released the lab to the queued admission.
    assert woken and woken[-1].startswith("QA host turn ready:")
    assert _current(test_db, other_id)["state"] == "waiting"


def test_failed_restore_keeps_custody_and_names_reset_recovery(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    execution_id, requirement_id, contract = _setup(test_db, tmp_path, monkeypatch)
    lease_id = int(contract["lease_id"])
    assert _call(
        handle_plan_execution_heartbeat, "qa.plan_execution.heartbeat", execution_id
    ).primary_success
    assert "qa_abort_restore_pending" in _abort(execution_id).error.message
    failed = {"restored": False, **RESTORED, "ok": False, "error_code": "starting_state_restore_failed"}
    ready = _ready(execution_id, requirement_id, contract, failed)
    assert ready.primary_success, ready.error
    current = _current(test_db, execution_id)
    assert current["state"] == "active"
    assert current["test_machine_lease_id"] == lease_id
    assert get_claim(test_db, lease_id).is_active
    retry = _abort(execution_id)
    assert not retry.primary_success
    assert "test-machine reset" in retry.error.message


def test_admission_before_check_in_aborts_at_once(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    execution_id, _requirement_id, contract = _setup(test_db, tmp_path, monkeypatch)
    aborted = _abort(execution_id)
    assert aborted.primary_success, aborted.error
    assert aborted.result_payload["state"] == "aborted"
    assert _current(test_db, execution_id)["test_machine_lease_id"] is None
