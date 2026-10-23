"""Public plan check-ins preserve unknown outcomes and exact cursor custody."""

from unittest import mock

import pytest

from runtime.api.domain.test_qa_plan_execution_fail_closed import (
    ACTOR,
    TEST_ITEM_REF,
    _begin_result,
)
from runtime.api.domain.test_qa_plan_execution_authority import _materialize_two_cases
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_core.domain import qa_plan_execution, qa_composed_dispatch
from yoke_core.domain.qa_plan_execution_checkin import QaPlanCommunicationUnknown
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_heartbeat
from yoke_core.domain.handlers.qa_plan_execution_reentry import handle_execution_reentry
from yoke_core.domain.qa_plan_execution_dispatch import call_plan_function


def _response(kwargs, *, result=None, code=None):
    return FunctionCallResponse(
        version="v1",
        function=kwargs["function_id"],
        request_id=kwargs["request_id"],
        success=code is None,
        result=result or {},
        error=FunctionError(code=code, message="response deadline elapsed")
        if code
        else None,
    )


def test_late_checkin_success_reuses_exact_request_before_one_case(monkeypatch):
    requests = []
    cases = []

    def transport(**kwargs):
        function = kwargs["function_id"]
        if function == "qa.plan_execution.begin":
            return _response(kwargs, result=_begin_result())
        if function == "qa.plan_execution.heartbeat":
            requests.append(kwargs)
            if len(requests) == 1:
                return _response(kwargs, code="https_transport_failed")
        return _response(kwargs)

    monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", transport)
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_checkin.time.sleep", lambda _: None
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_execution.execute_case_context",
        lambda case, **kw: (
            cases.append(case)
            or {"requirement_id": case["requirement_id"], "verdict": "pass"}
        ),
    )
    result = qa_plan_execution.execute_plan(
        public_ref=TEST_ITEM_REF, transition_id="implemented", actor=ACTOR
    )
    assert result["state"] == "passed"
    assert len(cases) == 1
    assert len(requests) == 2
    assert requests[0] == requests[1]
    assert (
        result["checkin_delivery"][0]["attempts"][0]["outcome"]
        == "https_transport_failed"
    )


@pytest.mark.parametrize("failure_phase", ["checkin", "recording"])
def test_unavailable_response_pauses_without_abort_or_duplicate_action(
    monkeypatch, failure_phase
):
    calls = []
    cases = []

    def transport(**kwargs):
        function = kwargs["function_id"]
        calls.append(function)
        if function == "qa.plan_execution.begin":
            return _response(kwargs, result=_begin_result())
        if function == (
            "qa.plan_execution.heartbeat"
            if failure_phase == "checkin"
            else "qa.plan_execution.advance"
        ):
            return _response(kwargs, code="https_transport_failed")
        return _response(kwargs)

    monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", transport)
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_checkin.time.sleep", lambda _: None
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_execution.execute_case_context",
        lambda case, **kw: (
            cases.append(case)
            or {"requirement_id": case["requirement_id"], "verdict": "pass"}
        ),
    )
    result = qa_plan_execution.execute_plan(
        public_ref=TEST_ITEM_REF, transition_id="implemented", actor=ACTOR
    )
    assert result["state"] == "outcome_unknown"
    assert result["results"] == []
    assert result["phase"] == failure_phase
    assert len(cases) == (0 if failure_phase == "checkin" else 1)
    assert calls[-1] == "qa.plan_execution.pause"
    assert "qa.plan_execution.abort" not in calls
    assert calls.count("qa.plan_execution.advance") <= 1


def test_permission_refusal_is_blocked_without_retry_or_case(monkeypatch):
    calls = []

    def transport(**kwargs):
        calls.append(kwargs["function_id"])
        return (
            _response(kwargs, result=_begin_result())
            if len(calls) == 1
            else _response(kwargs, code="permission_denied")
        )

    monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", transport)
    with mock.patch("yoke_core.domain.qa_case_execution.execute_case_context") as case:
        result = qa_plan_execution.execute_plan(
            public_ref=TEST_ITEM_REF, transition_id="implemented", actor=ACTOR
        )
    assert result["state"] == "blocked_on_precondition"
    assert "permission_denied" in result["recovery"]
    assert calls == ["qa.plan_execution.begin", "qa.plan_execution.heartbeat"]
    case.assert_not_called()


def _request(function, execution_id, **payload):
    return FunctionCallRequest(
        function=function,
        actor=ACTOR,
        target=TargetRef(kind="item", item_id=4401),
        payload={"execution_id": execution_id, **payload},
    )


def test_registered_pause_reentry_preserves_cursor_and_rejects_unknown_action():
    with test_database() as conn:
        ids = _materialize_two_cases(conn, item_id=4401)
        execution = begin_plan_execution(
            conn,
            item_id=4401,
            transition_id="implemented",
            actor_id=ACTOR.actor_id,
            session_id=ACTOR.session_id,
        )
        execution_id = execution["id"]
        checked = handle_plan_execution_heartbeat(
            _request("qa.plan_execution.heartbeat", execution_id)
        )
        assert checked.primary_success, checked.error
        assert "requirements" not in checked.result_payload
        assert "results" not in checked.result_payload
        unsafe = handle_execution_reentry(
            _request(
                "qa.plan_execution.resume", execution_id, transition_id="implemented"
            )
        )
        assert not unsafe.primary_success
        assert "qa_pause_unconfirmed" in unsafe.error.message
        for phase in ("checkin", "recording"):
            paused = handle_execution_reentry(
                _request(
                    "qa.plan_execution.pause",
                    execution_id,
                    phase=phase,
                    cursor=0,
                    request_id=f"lost-{phase}",
                    attempts=[{"outcome": "timeout"}],
                )
            )
            assert paused.primary_success, paused.error
            assert paused.result_payload["state"] == "waiting"
            resumed = handle_execution_reentry(
                _request(
                    "qa.plan_execution.resume",
                    execution_id,
                    transition_id="implemented",
                )
            )
            if phase == "recording":
                assert not resumed.primary_success
                assert "qa_action_outcome_unknown" in resumed.error.message
            else:
                assert resumed.primary_success, resumed.error
                assert resumed.result_payload["execution_id"] == execution_id
                assert resumed.result_payload["cursor_ordinal"] == 0
                assert [
                    case["requirement_id"]
                    for case in resumed.result_payload["requirements"]
                ] == ids
        durable = lock_plan_execution(conn, execution_id)
        assert durable["state"] == "waiting"
        assert durable["test_machine_lease_id"] is None
        assert (
            conn.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 1
        )
        conn.rollback()
        conn.execute(
            "UPDATE qa_plan_executions SET state='aborted' WHERE id=%s", (execution_id,)
        )
        conn.commit()
        terminal = handle_execution_reentry(
            _request(
                "qa.plan_execution.resume", execution_id, transition_id="implemented"
            )
        )
        assert not terminal.primary_success
        assert "qa_resume_terminal" in terminal.error.message


def test_unknown_checkin_keeps_request_identity_in_failure(monkeypatch):
    requests = []
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_checkin.time.sleep", lambda _: None
    )

    def transport(**kwargs):
        requests.append(kwargs["request_id"])
        return _response(kwargs, code="https_transport_failed")

    monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", transport)
    with pytest.raises(QaPlanCommunicationUnknown) as caught:
        call_plan_function(
            function_id="qa.plan_execution.heartbeat",
            target=TargetRef(kind="item", item_id=4401),
            payload={"execution_id": "exact-execution"},
            actor=ACTOR,
        )
    assert requests == [caught.value.request_id] * 2
    assert len(caught.value.attempts) == 2


def test_lost_server_success_reconciles_durable_ledger_without_second_write(
    monkeypatch,
):
    from runtime.api.fixtures.dispatch_actor import register_session_actor
    from runtime.api.fixtures.session_holdings import insert_item_claim
    from yoke_contracts.api.function_call import ActorContext
    from yoke_core.domain.yoke_function_dispatch import dispatch
    from yoke_core.domain.qa_plan_execution_lifecycle import heartbeat_plan_execution

    with test_database() as conn:
        _materialize_two_cases(conn, item_id=4401)
        session = "checkin-ledger-session"
        actor = ActorContext(
            actor_id=str(register_session_actor(conn, session)), session_id=session
        )
        insert_item_claim(conn, session, 4401)
        execution = begin_plan_execution(
            conn,
            item_id=4401,
            transition_id="implemented",
            actor_id=actor.actor_id,
            session_id=session,
        )
        requests = []

        def transport(**kwargs):
            requests.append(kwargs["request_id"])
            response = dispatch(
                FunctionCallRequest(
                    function=kwargs["function_id"],
                    actor=actor,
                    target=kwargs["target"],
                    request_id=kwargs["request_id"],
                    payload=kwargs["payload"],
                )
            )
            assert response.success, response.error
            if len(requests) == 1:
                # The server committed before the client response deadline.
                # Suppress only its reply, preserving real handler/ledger state.
                return _response(kwargs, code="https_transport_failed")
            return response

        monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", transport)
        monkeypatch.setattr(
            "yoke_core.domain.qa_plan_execution_checkin.time.sleep", lambda _: None
        )
        with mock.patch(
            "yoke_core.domain.qa_plan_execution_state.heartbeat_plan_execution",
            wraps=heartbeat_plan_execution,
        ) as write:
            receipt = call_plan_function(
                function_id="qa.plan_execution.heartbeat",
                target=TargetRef(kind="item", item_id=4401),
                payload={"execution_id": execution["id"]},
                actor=actor,
            )
        assert write.call_count == 1
        assert requests == [requests[0]] * 2
        assert receipt["execution_id"] == execution["id"]
        assert (
            conn.execute(
                "SELECT function_id FROM function_call_ledger WHERE request_id=%s",
                (requests[0],),
            ).fetchone()[0]
            == "qa.plan_execution.heartbeat"
        )
        conn.rollback()


def test_midcase_unknown_preserves_fixture_and_host_state():
    from runtime.api.domain.machine_qa_fixture_lifecycle_test_support import (
        FakeExecution,
        FakeFixtureRunner,
        case_contract,
    )
    from yoke_core.domain.machine_qa_fixture_lifecycle import (
        execute_case_with_fixture_lifecycle,
    )

    events = []
    unknown = QaPlanCommunicationUnknown(
        function_id="qa.plan_execution.heartbeat",
        request_id="in-case-checkin",
        attempts=[{"outcome": "timeout"}],
    )
    execution = FakeExecution(FakeFixtureRunner(events), events, primary_error=unknown)
    with pytest.raises(QaPlanCommunicationUnknown):
        execute_case_with_fixture_lifecycle(execution, case_contract())
    assert events == ["setup", "primary"]
    assert "close" not in events
