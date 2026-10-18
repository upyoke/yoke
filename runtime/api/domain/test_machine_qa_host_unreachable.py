"""A plan case whose host SSH cannot reach waits on the line, not an error."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
    materialize_installer_campaign,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.test_qa_host_health_turns import (
    ACTOR,
    ITEM_ID,
    MACHINE,
    _begin,
    _notices,
    _record,
    _wait_state,
)
from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
from yoke_contracts.machine_qa_execution import (
    HostControlExecutionContract,
    execution_contract_digest,
)
from yoke_contracts.machine_qa_failures import SSH_UNAVAILABLE, HostControlLocalError
from yoke_core.domain import machine_qa_plan_case_execution
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_submit
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import execute_machine_case_contract
from yoke_core.domain.qa_host_health import HOST_UNHEALTHY_REASON, host_unhealthy
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.work_claim_targets import make_qa_admission_target


def _unreachable(_material: Any) -> Any:
    raise HostControlLocalError(
        code=SSH_UNAVAILABLE,
        phase="host_facts_ssh",
        detail="SSH could not read the test user's host facts.",
        recovery_hint="Start the host, then verify it.",
        exit_code=255,
        stderr="ssh: connect to host 192.0.2.1 port 22: Operation timed out",
    )


def _run_unreachable(contract: dict[str, Any]) -> Any:
    register_host_control_factory(_unreachable)
    try:
        return execute_machine_case_contract(contract)
    finally:
        clear_host_control_factory()


def _plan(conn: Any, tmp_path: Path, monkeypatch: Any) -> tuple[dict, dict]:
    materialize_installer_campaign(conn, item_id=ITEM_ID)
    configure_test_machine(conn, tmp_path, monkeypatch)
    execution = begin_plan_execution(
        conn,
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    return execution, execution["roster"][0]


def _submit(execution: dict, case: dict, payload: dict[str, Any]) -> Any:
    return handle_plan_case_submit(
        FunctionCallRequest(
            function="test_machine.plan_case.submit",
            actor=ACTOR,
            target=TargetRef(kind="item", item_id=ITEM_ID),
            payload={
                "execution_id": str(execution["id"]),
                "ordinal": 0,
                "requirement_id": int(case["requirement_id"]),
                **payload,
            },
        )
    )


def test_unreachable_host_is_marked_unhealthy_and_the_plan_waits_until_verify(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    execution, case = _plan(test_db, tmp_path, monkeypatch)
    notices = _notices(monkeypatch)
    seed_qa_session(test_db, ACTOR.session_id, "operator")
    begun = _begin(execution, case)
    assert begun["state"] == "ready"

    submission = _run_unreachable(begun["execution"])
    result = submission.payload["results"][0]
    assert result["error_code"] == SSH_UNAVAILABLE
    assert result["evidence"]["case_started"] is False
    assert "Operation timed out" in result["evidence"]["host_unreachable"]["detail"]

    outcome = _submit(execution, case, submission.payload)
    assert outcome.primary_success, outcome.error
    waiting = outcome.result_payload
    assert waiting["state"] == "waiting"
    assert "result" not in waiting
    assert HOST_UNHEALTHY_REASON in waiting["host_wait"]["rationale"]
    assert SSH_UNAVAILABLE in waiting["host_wait"]["rationale"]
    assert "yoke test-machine verify" in waiting["host_wait"]["rationale"]
    assert host_unhealthy(test_db, MACHINE)["error_code"] == SSH_UNAVAILABLE
    target = make_qa_admission_target(MACHINE)
    assert active_claim(test_db, target) is None
    no_verdict = test_db.execute(
        "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s",
        (int(case["requirement_id"]),),
    ).fetchone()[0]
    assert no_verdict == 0

    # Re-running the plan queues again instead of dispatching to the host.
    begin_plan_execution(
        test_db,
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    assert _begin(execution, case)["state"] == "waiting"
    assert notices == []

    # The operator starts the host; a successful verify heals it and wakes us.
    healing = acquire(test_db, target, "operator")
    _record(test_db, "verify", "verified")
    release(test_db, healing.id, "test-machine-verify-complete")
    assert host_unhealthy(test_db, MACHINE) is None
    assert active_claim(test_db, target).session_id == ACTOR.session_id
    assert _wait_state(test_db, ACTOR.session_id) == "reserved"
    assert len(notices) == 1 and "QA host turn ready" in notices[0]


def test_single_case_contract_keeps_raising_the_named_failure(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    execution, case = _plan(test_db, tmp_path, monkeypatch)
    plan = HostControlExecutionContract.model_validate(
        _begin(execution, case)["execution"]
    )
    plan_cursor = (
        "plan_execution_id",
        "continues_execution_id",
        "roster_digest",
        "ordinal",
        "case_position",
        "baseline_position",
    )
    single = plan.model_copy(update={"operation": "case", **dict.fromkeys(plan_cursor)})
    single = single.model_copy(
        update={"contract_digest": execution_contract_digest(single)}
    )
    contract = single.model_dump(mode="json")
    with pytest.raises(HostControlLocalError) as caught:
        _run_unreachable(contract)
    assert caught.value.code == SSH_UNAVAILABLE


def test_plan_runner_returns_the_waiting_case_from_submit(monkeypatch: Any) -> None:
    host_wait = {"machine": "windows-lab", "position": 1, "line_length": 1}

    def dispatch(function_id: str, **_kwargs: Any) -> dict[str, Any]:
        if function_id == "test_machine.plan_case.begin":
            return {"state": "ready", "execution": {"lease_id": 1}}
        assert function_id == "test_machine.plan_case.submit"
        return {"state": "waiting", "host_wait": host_wait}

    class Submission:
        payload: dict[str, Any] = {}

        def cleanup_artifacts(self) -> None:
            pass

    monkeypatch.setattr(machine_qa_plan_case_execution, "_dispatch", dispatch)
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_local_execution.execute_machine_case_contract",
        lambda *_a, **_k: Submission(),
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_host_control.register_test_machine_host_control",
        lambda: None,
    )
    case = machine_qa_plan_case_execution.execute_plan_machine_case(
        {"requirement_id": 7, "public_ref": "YOK-1"},
        execution_id="e",
        ordinal=0,
        actor=ACTOR,
    )
    assert case["verdict"] == "waiting"
    assert case["host_wait"] == host_wait
    assert "Queued for QA host windows-lab" in case["recovery"]
