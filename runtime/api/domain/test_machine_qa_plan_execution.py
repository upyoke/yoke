"""One uninterrupted Test Mac lease across an ordered QA plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    configure_test_machine,
    materialize_installer_campaign,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.machine_qa_plan_case import (
    handle_plan_case_begin,
    handle_plan_case_submit,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    execute_machine_case_contract,
)
from yoke_core.domain import machine_qa_execution_protocol
from yoke_core.domain.coordination_claims import acquire, release
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    finish_plan_execution,
    lock_plan_execution,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_core.domain.work_claim_targets import make_qa_admission_target


ACTOR = ActorContext(actor_id="2", session_id="session-machine-plan")


def _request(
    function: str,
    *,
    item_id: int,
    execution_id: str,
    ordinal: int,
    requirement_id: int,
    payload: dict[str, Any] | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ACTOR,
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "execution_id": execution_id,
            "ordinal": ordinal,
            "requirement_id": requirement_id,
            **(payload or {}),
        },
    )


def _active_lease_count(conn: Any) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE released_at IS NULL "
            "AND target_kind = 'qa_admission'"
        ).fetchone()[0]
    )


def _execute_begin_contract(response: Any) -> Any:
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "ready"
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        return execute_machine_case_contract(response.result_payload["execution"])
    finally:
        clear_host_control_factory()


def test_ordered_plan_reuses_one_machine_lease_until_final_abort(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    item_id = 4420
    materialize_installer_campaign(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    execution_id = str(execution["id"])
    first_case, second_case = execution["roster"][:2]

    first_begin = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=int(first_case["requirement_id"]),
        )
    )
    assert first_begin.primary_success, first_begin.error
    assert first_begin.result_payload["state"] == "ready"
    first_contract = first_begin.result_payload["execution"]
    first_lease_id = int(first_contract["lease_id"])
    assert first_contract["plan_execution_id"] == execution_id
    assert first_contract["roster_digest"] == execution["roster_digest"]
    assert first_contract["ordinal"] == 0
    assert first_contract["case_position"] == first_case["case_position"]
    assert first_contract["baseline_position"] == first_case["baseline_position"]
    first_submission = _execute_begin_contract(first_begin)
    first_submit_request = _request(
        "test_machine.plan_case.submit",
        item_id=item_id,
        execution_id=execution_id,
        ordinal=0,
        requirement_id=int(first_case["requirement_id"]),
        payload=first_submission.payload,
    )
    try:
        first_submit = handle_plan_case_submit(first_submit_request)
    finally:
        first_submission.cleanup_artifacts()
    assert first_submit.primary_success, first_submit.error
    assert first_submit.result_payload["cursor_ordinal"] == 1
    assert _active_lease_count(test_db) == 1

    second_begin = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=1,
            requirement_id=int(second_case["requirement_id"]),
        )
    )
    assert int(second_begin.result_payload["execution"]["lease_id"]) == (first_lease_id)
    second_submission = _execute_begin_contract(second_begin)
    try:
        second_submit = handle_plan_case_submit(
            _request(
                "test_machine.plan_case.submit",
                item_id=item_id,
                execution_id=execution_id,
                ordinal=1,
                requirement_id=int(second_case["requirement_id"]),
                payload=second_submission.payload,
            )
        )
    finally:
        second_submission.cleanup_artifacts()
    assert second_submit.primary_success, second_submit.error
    assert second_submit.result_payload["cursor_ordinal"] == 2
    assert _active_lease_count(test_db) == 1

    current = lock_plan_execution(test_db, execution_id)
    finish_plan_execution(
        test_db,
        current,
        state="aborted",
        reason="test-plan-finished",
    )
    assert _active_lease_count(test_db) == 0
    assert lock_plan_execution(test_db, execution_id)["state"] == "aborted"

    replay = handle_plan_case_submit(first_submit_request)
    assert replay.primary_success, replay.error
    assert replay.result_payload["result"] == first_submit.result_payload["result"]
    assert replay.result_payload["cursor_ordinal"] == 2
    assert _active_lease_count(test_db) == 0


def test_machine_lease_waiting_state_resumes_at_the_same_cursor(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    item_id = 4421
    materialize_installer_campaign(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    case = execution["roster"][0]
    seed_qa_session(test_db, "another-session")
    held = acquire(
        test_db,
        make_qa_admission_target("mac-mini-lab"),
        "another-session",
    )

    waiting = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=str(execution["id"]),
            ordinal=0,
            requirement_id=int(case["requirement_id"]),
        )
    )
    assert waiting.primary_success, waiting.error
    assert waiting.result_payload["state"] == "waiting"
    assert waiting.result_payload["execution_id"] == str(execution["id"])
    assert waiting.result_payload["cursor_ordinal"] == 0
    lease_context = waiting.result_payload["lease_context"]
    assert lease_context["holder_session_id"] == "session another-session"
    assert "heartbeat age" in lease_context["wait_message"]
    assert "yoke coordination-claim release" in lease_context["wait_message"]
    stored = lock_plan_execution(test_db, str(execution["id"]))
    assert stored["state"] == "waiting"
    assert stored["machine_lease_id"] is None

    release(test_db, held.id, "test-holder-finished")
    resumed = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    assert resumed["state"] == "active"
    assert resumed["cursor_ordinal"] == 0
    ready = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=str(execution["id"]),
            ordinal=0,
            requirement_id=int(case["requirement_id"]),
        )
    )
    assert ready.primary_success, ready.error
    assert ready.result_payload["state"] == "ready"
    assert _active_lease_count(test_db) == 1
    finish_plan_execution(
        test_db,
        lock_plan_execution(test_db, str(execution["id"])),
        state="aborted",
        reason="test-finished",
    )
    assert _active_lease_count(test_db) == 0


def test_machine_lease_acquisition_defers_commit_until_plan_attachment(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    item_id = 4422
    materialize_installer_campaign(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    case = execution["roster"][0]

    with mock.patch.object(
        machine_qa_execution_protocol,
        "begin_host_control_execution",
        wraps=machine_qa_execution_protocol.begin_host_control_execution,
    ) as begin:
        ready = handle_plan_case_begin(
            _request(
                "test_machine.plan_case.begin",
                item_id=item_id,
                execution_id=str(execution["id"]),
                ordinal=0,
                requirement_id=int(case["requirement_id"]),
            )
        )

    assert ready.primary_success, ready.error
    deferred = begin.call_args.args[0]
    assert type(deferred).__name__ == "_CommitDeferredConnection"
    stored = lock_plan_execution(test_db, str(execution["id"]))
    assert stored["state"] == "active"
    assert stored["machine_lease_id"] == ready.result_payload["execution"]["lease_id"]
    finish_plan_execution(
        test_db,
        stored,
        state="aborted",
        reason="test-finished",
    )
    assert _active_lease_count(test_db) == 0
