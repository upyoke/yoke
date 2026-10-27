"""Hostless exploration captures and settles without any host authority."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_qa_plan_standalone_execution import _begin
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_contracts.qa_case_starting_state import needs_test_machine, StartingStateError, normalize_starting_state
from yoke_core.domain.agent_mission_brief import _walker_dispatch
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.machine_reset_debt import record_execution_reset_debt
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution, finish_plan_execution
from yoke_core.domain.qa_plan_review import begin_plan_review


def _mission(conn, *, with_host=False):
    plan = create_plan(conn, project="yoke", slug="manual-proof", name="Controller exploration")
    cases = [{
        "case_key": "controller", "position": 1, "method_id": "exploratory-mission",
        "instructions": "Explore controller evidence", "expected_outcome": "Rank findings",
        "method_config": {"executor": "informed_subagent"},
    }]
    if with_host:
        cases.insert(0, {"case_key": "host", "position": 1,
            "method_id": "machine-state-check", "instructions": "Check host",
            "expected_outcome": "Assertion passes", "host_baselines": ["fresh-host"],
            "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}],
                              "os": "macos", "test_machine": "mac-mini-lab"}})
        cases[1]["position"] = 2
    replace_plan_cases(conn, plan_id=plan["id"], cases=cases)
    conn.commit()
    return _begin(conn, test_machine=None if with_host else "unused-run-pin")


@pytest.mark.parametrize("abort", [False, True])
def test_controller_mission_records_docket_and_never_owes_reset(test_db, abort):
    execution = _mission(test_db)
    case = execution["roster"][0]
    assert not needs_test_machine(case)
    request = FunctionCallRequest(
        function="test_machine.plan_case.begin",
        actor=ActorContext(actor_id="7", session_id="manual-owner"),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={"execution_id": execution["id"], "ordinal": 0,
                 "requirement_id": case["requirement_id"]},
    )
    begun = handle_plan_case_begin(request)
    assert begun.primary_success, begun.error
    result = begun.result_payload["result"]
    replay = handle_plan_case_begin(request)
    assert replay.primary_success, replay.error
    assert replay.result_payload["result"] == result
    execution = lock_plan_execution(test_db, execution["id"])
    assert execution["test_machine_lease_id"] is None
    raw = test_db.execute("SELECT raw_result FROM qa_runs WHERE id=%s", (result["run_id"],)).fetchone()[0]
    assert "host_control_submission" not in json.loads(raw)
    if abort:
        finish_plan_execution(test_db, execution, state="aborted", reason="controller stop")
    else:
        assert begin_plan_review(test_db, execution)
        execution = lock_plan_execution(test_db, execution["id"])
        assert execution["state"] == "awaiting_walk_review"
    assert test_db.execute("SELECT COUNT(*) FROM qa_artifacts WHERE artifact_type='starting_state_restore'").fetchone()[0] == 0
    assert test_db.execute("SELECT COUNT(*) FROM test_machine_operation_receipts WHERE operation='reset_owed'").fetchone()[0] == 0


@pytest.mark.parametrize("declaration", [
    {"method_config": {"test_machine": "test-mac"}},
    {"method_config": {"test_machines": ["test-mac"]}},
    {"method_config": {"os": "macos"}},
    {"capability_requirements": ["test-machine:test-mac"]},
    {"host_baselines": ["fresh-host"]},
])
def test_host_declarations_require_a_machine(declaration):
    assert needs_test_machine({"runner_id": "agent_mission", **declaration})


def test_named_host_without_starting_state_refuses():
    with pytest.raises(StartingStateError):
        normalize_starting_state(case_key="host", runner_id="agent_mission",
                                 method_config={"test_machine": "test-mac"},
                                 host_baselines=[], starting_state=None, starting_state_reason=None)


def test_controller_brief_has_only_controller_authority():
    brief = _walker_dispatch({"requirement_id": 1, "capture_run_id": 2,
                              "executor": "informed_subagent", "instructions": "Explore",
                              "expected_outcome": "Findings"}, execution_id="walk",
                             subject_flag="--project example", browser_settings={}, execution_target={})
    assert brief["location"] == "controller"
    assert not {"walk_start_command", "walk_end_command", "host_command"} & brief.keys()


def test_reset_debt_uses_last_host_case_in_mixed_roster(monkeypatch):
    from yoke_core.domain import machine_reset_debt as debt
    calls = []
    monkeypatch.setattr(debt, "record_reset_owed", lambda conn, **kw: calls.append(kw))
    lease = SimpleNamespace(id=3, target=SimpleNamespace(test_machine="test-mac"))
    host = {"runner_id": "host_control", "host_baseline": "shell-preconfigured"}
    controller = {"runner_id": "agent_mission", "method_config": {}}
    record_execution_reset_debt(None, {"roster": [controller], "cursor_ordinal": 1}, [lease])
    assert calls == []
    record_execution_reset_debt(None, {"roster": [host, controller], "cursor_ordinal": 2}, [lease])
    assert calls[0]["case"] == host


def test_plan_routes_controller_mission_without_selected_machine():
    from yoke_core.domain.qa_plan_execution_run import execute_begun_plan

    calls = []
    case = {"requirement_id": 1, "runner_id": "agent_mission", "method_config": {},
            "case_key": "controller", "case_position": 1, "baseline_position": 0, "plan_id": 1}
    def call(**kwargs):
        calls.append(kwargs)
        if kwargs["function_id"] == "test_machine.plan_case.begin":
            assert "test_machine" not in kwargs["payload"]
            return {"result": {"requirement_id": 1, "run_id": 2, "case_outcome": "needs_review"}}
        if kwargs["function_id"] == "qa.plan_review.begin":
            return {"review_bundle": {"bundle_id": "review"}, "state": "awaiting_walk_review"}
        return {}
    begun = SimpleNamespace(requirements=[case], cursor=0, resolved_base_url=None,
                            recorded_results=[], recorded_ordinals=[],
                            selected_machine="test-mac", host_free_cases_ahead=False)
    result = execute_begun_plan(execution={"execution_id": "run"}, begun=begun,
        target=TargetRef(kind="global", project_id="example"),
        resolved_actor=ActorContext(actor_id="7", session_id="owner"),
        transition_id=None, expected_branch=None, expected_sha=None,
        timeout_seconds=30, checkout_path=None, allow_tree_mismatch=False,
        call_plan_function=call)
    assert result["state"] == "awaiting_walk_review"
    assert [c["function_id"] for c in calls] == ["qa.plan_execution.heartbeat",
        "test_machine.plan_case.begin", "qa.plan_review.begin"]
