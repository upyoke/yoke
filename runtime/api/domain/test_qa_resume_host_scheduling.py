"""Host admission uses platform affinity without a command-wide constraint."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_core.domain.qa_plan_host_leases import begin_case_host_contract
from yoke_core.domain.qa_plan_execution_begin_validation import validate_begun_execution


@pytest.mark.parametrize("retained", ["linux-lab", None])
def test_resumed_platform_retains_host_and_new_platform_selects_normally(
    monkeypatch, retained
):
    from yoke_core.domain import machine_qa_execution_protocol as protocol
    from yoke_core.domain import qa_plan_execution_lifecycle as lifecycle

    case = {
        "project": "example",
        "project_id": 1,
        "runner_id": "agent_mission",
        "method_config": {"os": "linux"},
    }
    other = {**case, "method_config": {"os": "macos"}}
    execution = {"id": "walk", "roster": [case, other], "machine_lease_id": 7}
    conn = Mock()
    monkeypatch.setattr(
        "yoke_core.domain.qa_resume_machine.execution_machine", lambda *a: retained
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_host_leases.get_claim",
        lambda *a: SimpleNamespace(target=SimpleNamespace(machine_id="test-mac")),
    )
    released = Mock()
    monkeypatch.setattr("yoke_core.domain.qa_plan_host_leases.release", released)
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_host_leases.release_execution_hosts", Mock()
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_plan_protocol.plan_case_contract_arguments",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(protocol, "commit_deferred_connection", lambda c: c)
    begin = Mock(return_value=SimpleNamespace(lease_id=9))
    monkeypatch.setattr(protocol, "begin_host_control_execution", begin)
    monkeypatch.setattr(lifecycle, "set_plan_machine_lease", Mock())

    contract = begin_case_host_contract(
        conn, execution, case, ordinal=0, machine=None, actor_id="1", session_id="owner"
    )
    assert contract.lease_id == 9
    assert begin.call_args.kwargs["machine"] == retained
    assert begin.call_args.kwargs["host_cases"] == [case]
    assert execution["machine_lease_id"] is None
    released.assert_called_once_with(conn, 7, "qa-case-host-change", commit=False)


def test_resumed_single_platform_keeps_live_lease(monkeypatch):
    from yoke_core.domain import machine_qa_plan_protocol as protocol

    execution = {"id": "single", "roster": [], "machine_lease_id": 7}
    case = {"project": "example", "method_config": {"os": "linux"}}
    monkeypatch.setattr(
        "yoke_core.domain.qa_resume_machine.execution_machine", lambda *a: "linux-lab"
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_host_leases.get_claim",
        lambda *a: SimpleNamespace(target=SimpleNamespace(machine_id="linux-lab")),
    )
    monkeypatch.setattr(protocol, "plan_case_contract_arguments", lambda *a, **k: {})
    continuation = Mock()
    monkeypatch.setattr(protocol, "continue_plan_host_control_execution", continuation)
    begin_case_host_contract(
        Mock(),
        execution,
        case,
        ordinal=0,
        machine=None,
        actor_id="1",
        session_id="owner",
    )
    assert continuation.call_args.kwargs["lease_id"] == 7
    assert continuation.call_args.kwargs["machine"] == "linux-lab"


def test_begin_accepts_multi_host_roster_without_a_global_pin(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_begin_validation.resolve_execution_base_url",
        lambda *a: "https://example.test",
    )
    result = validate_begun_execution(
        {
            "requirements": [
                {"method_config": {"machine": host}}
                for host in ["linux-lab", "test-mac"]
            ],
            "execution_target": {},
        },
        machine=None,
        base_url="",
    )
    assert result.selected_machine is None


def test_standalone_multi_platform_resume_uses_durable_hosts(
    test_db, tmp_path, monkeypatch
):
    import json
    from runtime.api.domain.machine_qa_host_test_support import (
        TEST_MACHINE_SETTINGS,
        _terminal_recipe,
        configure_test_machine,
    )
    from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
    from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
    from yoke_core.domain.qa_standalone_execution import begin_standalone_execution
    from yoke_core.domain.qa_plan_execution_state import (
        advance_plan_execution,
        finish_plan_execution,
    )
    from yoke_core.domain.qa_host_turns import record_host_wait

    configure_test_machine(test_db, tmp_path, monkeypatch)
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session

    seed_qa_session(test_db, "session-machine-plan", messageable=True)
    replace_test_machine_settings(
        test_db,
        project="yoke",
        machine="linux-lab",
        settings={**TEST_MACHINE_SETTINGS, "resource_name": "linux-lab", "os": "linux"},
        base_settings=None,
    )
    from runtime.api.domain.test_deployment_qa_stage_execution import _environment

    _environment(test_db)
    plan = create_plan(
        test_db, project="yoke", slug="platform-walk", target_environment="stage"
    )
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": key,
                "method_id": "terminal-check",
                "instructions": f"Run the {platform} check.",
                "expected_outcome": "The check passes.",
                "method_config": {**_terminal_recipe(), "os": platform},
                "entry_surface": "printf done",
                "required_completion": "complete",
                "starting_state": "as_is",
                "starting_state_reason": "Read host identity without changing its state.",
            }
            for key, platform in [
                ("linux-first", "linux"),
                ("mac", "macos"),
                ("linux-resume", "linux"),
            ]
        ],
    )

    def begin():
        return begin_standalone_execution(
            test_db,
            plan="platform-walk",
            project="yoke",
            actor_id="1",
            session_id="session-machine-plan",
        )

    execution = begin()
    selected = []
    for ordinal, host in enumerate(["linux-lab", "mac-mini-lab", "linux-lab"]):
        case = execution["roster"][ordinal]
        contract = begin_case_host_contract(
            test_db,
            execution,
            case,
            ordinal=ordinal,
            machine=None,
            actor_id="1",
            session_id="session-machine-plan",
        )
        selected.append(contract.settings["resource_name"])
        assert contract.settings["resource_name"] == host
        requirement_id = case["requirement_id"]
        run_id = test_db.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,raw_result,started_at,completed_at,created_at) "
            "VALUES (%s,'host_control','plan_case','pass',%s,now(),now(),now()) RETURNING id",
            (requirement_id, json.dumps({"evidence": {"machine": host}})),
        ).fetchone()[0]
        advance_plan_execution(
            test_db,
            execution,
            ordinal=ordinal,
            requirement_id=requirement_id,
            result={
                "requirement_id": requirement_id,
                "case_outcome": "passed",
                "run_id": run_id,
            },
        )
        if ordinal == 0:
            wait = record_host_wait(
                test_db, execution, machine="mac-mini-lab", rationale="next platform"
            )
            assert "--machine" not in wait["host_wait"]["resume_command"]
            resumed = begin()
            assert resumed["id"] == execution["id"]
            execution = resumed
    assert selected == ["linux-lab", "mac-mini-lab", "linux-lab"]
    finish_plan_execution(test_db, execution, state="completed", reason="test-complete")
