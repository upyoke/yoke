"""Fail-closed boundaries around client-local ordered-plan side effects."""

from __future__ import annotations

from unittest import mock
from types import SimpleNamespace

import pytest

from runtime.api.domain.qa_plan_execution_test_support import (
    TEST_EXECUTION_TARGET,
    TEST_ITEM_ID,
    TEST_ITEM_REF,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_case_execution, qa_plan_execution


ACTOR = ActorContext(actor_id="7", session_id="ordered-failure")
CASE = {
    "requirement_id": 11,
    "item_id": TEST_ITEM_ID,
    "plan_id": 3,
    "case_key": "command",
    "case_position": 1,
    "baseline_position": 1,
    "host_baseline": None,
    "runner_id": "worktree_run",
}


def _begin_result() -> dict:
    return {
        "execution_id": "execution-1",
        "item_id": 42,
        "transition_id": "implemented",
        "state": "active",
        "roster_digest": "digest",
        "cursor_ordinal": 0,
        "execution_target": TEST_EXECUTION_TARGET,
        "execution_target_digest": "target-digest",
        "requirements": [CASE],
        "results": [],
    }


def test_begin_denial_prevents_every_local_runner_side_effect() -> None:
    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=qa_plan_execution.QaPlanExecutionError("claim denied"),
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
        ) as execute,
    ):
        with pytest.raises(
            qa_plan_execution.QaPlanExecutionError,
            match="claim denied",
        ):
            qa_plan_execution.execute_plan(
                public_ref=TEST_ITEM_REF,
                transition_id="implemented",
                actor=ACTOR,
            )
    execute.assert_not_called()


def test_advance_failure_aborts_and_never_reports_the_case_complete() -> None:
    calls: list[str] = []

    def dispatch(**kwargs):
        function_id = kwargs["function_id"]
        calls.append(function_id)
        if function_id == "qa.plan_execution.begin":
            return _begin_result()
        if function_id == "qa.plan_execution.advance":
            raise qa_plan_execution.QaPlanExecutionError(
                "cursor persistence unavailable"
            )
        return {}

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=dispatch,
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
            return_value={
                "requirement_id": 11,
                "runner_id": "worktree_run",
                "verdict": "pass",
                "case_outcome": "passed",
            },
        ),
    ):
        result = qa_plan_execution.execute_plan(
            public_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=ACTOR,
        )

    assert result["state"] == "error"
    assert result["results"][0]["case_outcome"] == "error"
    assert "cursor persistence unavailable" in result["results"][0]["error"]
    assert calls == [
        "qa.plan_execution.begin",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.advance",
        "qa.plan_execution.abort",
    ]


def test_interrupt_aborts_before_propagating_to_the_operator() -> None:
    calls: list[str] = []

    def dispatch(**kwargs):
        function_id = kwargs["function_id"]
        calls.append(function_id)
        if function_id == "qa.plan_execution.begin":
            return _begin_result()
        return {}

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=dispatch,
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
            side_effect=KeyboardInterrupt,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        qa_plan_execution.execute_plan(
            public_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=ACTOR,
        )

    assert calls == [
        "qa.plan_execution.begin",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.abort",
    ]


def test_busy_checkin_during_mission_setup_preserves_execution() -> None:
    from yoke_core.domain import machine_qa_plan_case_execution as mission
    from yoke_core.domain.agent_mission_preparation import prepare_mission

    calls = []
    contract = SimpleNamespace(
        baselines=[],
        plan_execution_id="execution-1",
        lease_id=1,
        contract_digest="digest",
    )

    def dispatch(**kwargs):
        calls.append(kwargs["function_id"])
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                **_begin_result(),
                "requirements": [{**CASE, "runner_id": "agent_mission"}],
            }
        return {}

    def mission_dispatch(function_id, **kwargs):
        calls.append(function_id)
        assert function_id == "qa.plan_execution.heartbeat"
        try:
            raise qa_plan_execution.QaPlanExecutionError(
                "qa.plan_execution.heartbeat failed (plan_execution_heartbeat_failed): "
                "qa_checkin_busy: preserve custody and retry the same execution"
            )
        except qa_plan_execution.QaPlanExecutionError as exc:
            raise mission.MachinePlanCaseDispatchError(str(exc)) from exc

    def prepare(raw_contract, *, progress_callback):
        def execution_factory(*args, **kwargs):
            progress_callback()
            pytest.fail("busy setup continued")

        return prepare_mission(
            contract,
            execution_factory=execution_factory,
            scratch_factory=mock.Mock(side_effect=AssertionError("scratch after busy")),
        )

    with (
        mock.patch.object(
            qa_plan_execution, "_call_plan_function", side_effect=dispatch
        ),
        mock.patch.object(
            mission, "_begin", return_value={"state": "ready", "execution": {}}
        ),
        mock.patch.object(mission, "refreshed_case_contract", return_value={}),
        mock.patch.object(mission, "_dispatch", side_effect=mission_dispatch),
        mock.patch(
            "yoke_core.domain.machine_qa_host_control.register_test_machine_host_control"
        ),
        mock.patch(
            "yoke_core.domain.machine_qa_local_execution.prepare_agent_mission_contract",
            side_effect=prepare,
        ),
    ):
        result = qa_plan_execution.execute_plan(
            public_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=ACTOR,
        )

    assert result["state"] == "blocked_on_precondition"
    assert result["execution_id"] == "execution-1"
    assert result["results"] == []
    assert "qa_checkin_busy:" in result["recovery"]
    assert calls == [
        "qa.plan_execution.begin",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.heartbeat",
    ]


def test_real_mission_setup_failure_keeps_terminal_reason() -> None:
    from yoke_core.domain.agent_mission_preparation import prepare_mission

    contract = SimpleNamespace(
        baselines=[],
        plan_execution_id="execution-1",
        lease_id=1,
        contract_digest="digest",
    )
    result = prepare_mission(
        contract,
        execution_factory=mock.Mock(
            side_effect=qa_plan_execution.QaPlanExecutionError(
                "credentials unavailable"
            )
        ),
        scratch_factory=mock.Mock(side_effect=AssertionError("scratch after failure")),
    )
    assert result["preparation"]["ok"] is False
    failure = result["preparation"]["evidence"]["preparation_failure"]
    assert failure["diagnostic"] == "QaPlanExecutionError: credentials unavailable"
