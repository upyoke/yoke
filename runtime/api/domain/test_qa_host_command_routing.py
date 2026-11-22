"""Host Commands are selected by OS: routing, run pins and stored host names."""

from unittest.mock import Mock

import pytest

from yoke_core.domain import qa_case_execution as cases
from yoke_core.domain import qa_case_mission_execution as missions
from yoke_core.domain import qa_plan_command_case as commands
from yoke_core.domain.qa_plan_host_free_cases import is_host_free_case

WINDOWS_HOST = "windows-native-lab-2"


def _command(**config):
    return {
        "requirement_id": 61,
        "runner_id": "worktree_run",
        "project": "example",
        "public_ref": "EX-7",
        "workflow_transition_id": "reviewing-implementation",
        "method_config": {"command": "true", **config},
    }


def _host_command(**config):
    return {
        **_command(os="windows", **config),
        "starting_state": "baseline",
        "host_baseline": "fresh-host",
        "host_baselines": ["fresh-host"],
    }


@pytest.fixture
def routed(monkeypatch):
    """Serve the case context and record which runner received it."""

    def serve(case):
        monkeypatch.setattr(cases, "fetch_case_execution_context", lambda *a, **k: case)
        plan = Mock(return_value={"state": "completed", "requirement_id": 61})
        local = Mock(return_value={"verdict": "pass", "requirement_id": 61})
        monkeypatch.setattr(missions, "execute_single_plan_case", plan)
        monkeypatch.setattr(cases, "execute_case_context", local)
        return plan, local

    return serve


def test_stage_credit_sends_an_os_command_to_the_host_command_executor(routed):
    plan, local = routed(_host_command())
    cases.execute_case(61)
    assert plan.call_args.kwargs["kind"] == "host_command"
    local.assert_not_called()


def test_stage_credit_runs_a_command_without_os_locally(routed):
    plan, local = routed(_command())
    cases.execute_case(61)
    local.assert_called_once()
    plan.assert_not_called()


def test_case_run_pin_on_an_os_command_reaches_the_plan_admission(monkeypatch):
    case = _host_command()
    monkeypatch.setattr(cases, "fetch_case_execution_context", lambda *a, **k: case)
    execute = Mock(return_value={"execution_id": "single", "state": "completed"})
    monkeypatch.setattr(missions, "execute_plan", execute)
    cases.execute_case(61, test_machine=WINDOWS_HOST)
    assert execute.call_args.kwargs["test_machine"] == WINDOWS_HOST


def test_case_run_pin_on_a_local_command_is_not_used(monkeypatch):
    monkeypatch.setattr(cases, "fetch_case_execution_context", lambda *a, **k: _command())
    with pytest.raises(cases.QaCaseExecutionError, match="test_machine_not_used"):
        cases.execute_case(61, test_machine=WINDOWS_HOST)


@pytest.mark.parametrize(
    "case",
    [
        _command(test_machine="windows-native-lab"),
        _host_command(test_machine="windows-native-lab"),
        _host_command(test_machines=["linux-lab", "windows-native-lab"]),
        {**_command(), "required_capability_kinds": ["test-machine:linux-lab"]},
    ],
)
def test_case_run_refuses_a_stored_host_name_before_any_runner(monkeypatch, case):
    monkeypatch.setattr(cases, "fetch_case_execution_context", lambda *a, **k: case)
    plan = Mock()
    monkeypatch.setattr(missions, "execute_plan", plan)
    monkeypatch.setattr(cases, "execute_case_context", plan)
    with pytest.raises(cases.QaCaseExecutionError, match="test_machine_name_forbidden"):
        cases.execute_case(61)
    plan.assert_not_called()


def test_an_os_command_is_never_host_free_work():
    assert is_host_free_case(_command())
    assert not is_host_free_case(_host_command())
    assert not is_host_free_case({**_command(), "starting_state": "inherit"})


def test_only_host_commands_heartbeat_the_plan():
    assert "liveness" in commands.command_liveness(_host_command(), lambda: None)
    assert commands.command_liveness(_command(), lambda: None) == {}


@pytest.mark.parametrize("pin", [None, WINDOWS_HOST])
def test_an_os_command_begins_with_only_the_operator_run_pin(monkeypatch, pin):
    calls = []

    def dispatch(function_id, **kwargs):
        calls.append(kwargs["payload"])
        return {"state": "waiting", "host_wait": {}}

    monkeypatch.setattr(commands, "_dispatch", dispatch)
    monkeypatch.setattr(commands, "_waiting_case", lambda *a, **k: {"case_outcome": "waiting"})
    options = {"test_machine": pin} if pin else {}
    result = commands.begin_command_host(
        _host_command(), execution_id="plan", ordinal=0, target="subject", actor="o", **options
    )
    assert result == {"case_outcome": "waiting"}
    assert calls[0].get("test_machine") == pin
    assert ("test_machine" in calls[0]) == bool(pin)


def test_lost_custody_owes_the_reset_of_an_os_command(monkeypatch):
    from types import SimpleNamespace

    from yoke_core.domain import machine_reset_debt as debt

    owed = []
    monkeypatch.setattr(debt, "record_reset_owed", lambda conn, **kw: owed.append(kw))
    host = _host_command()
    execution = {"cursor_ordinal": 1, "roster": [host, _command()]}
    lease = SimpleNamespace(id=4, target=SimpleNamespace(test_machine=WINDOWS_HOST))
    debt.record_execution_reset_debt(None, execution, [lease])
    assert owed == [{"case": host, "test_machine": WINDOWS_HOST, "lease_id": 4}]
