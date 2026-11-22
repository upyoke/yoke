"""Declared-host Commands reuse plan admission and reject foreign custody."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import host_lease_walk_heartbeat as walk_lease
from yoke_core.domain import machine_qa_operation_lease as operations
from yoke_core.domain import qa_plan_command_case as commands
from yoke_core.domain.machine_qa_case_machine import (
    MachineConstraintError,
    normalize_config_machine,
)


def test_command_declares_its_host_by_os_and_never_by_name():
    normalize_config_machine("command", {"command": "yoke test-machine reset", "os": "linux"})
    with pytest.raises(MachineConstraintError, match="test_machine_name_forbidden"):
        normalize_config_machine(
            "command", {"command": "yoke test-machine reset", "test_machine": "linux-lab"}
        )


def test_declared_host_command_cannot_run_as_host_free_work():
    from yoke_core.domain.qa_plan_host_free_cases import is_host_free_case

    assert is_host_free_case({"runner_id": "worktree_run", "method_config": {}})
    assert not is_host_free_case(
        {
            "runner_id": "worktree_run",
            "method_config": {"os": "linux"},
            "host_baselines": ["fresh-host"],
        }
    )


@pytest.fixture
def owned_plan(monkeypatch):
    execution = {
        "id": "plan-execution",
        "state": "active",
        "session_id": "owner",
        "actor_id": "1",
        "cursor_ordinal": 0,
        "roster": [{"runner_id": "worktree_run", "project": "yoke"}],
    }
    lease = SimpleNamespace(
        id=8, is_active=True, reason="", target=SimpleNamespace(test_machine="linux-lab")
    )
    monkeypatch.setattr(operations, "get_claim", lambda *_: lease)
    monkeypatch.setattr(walk_lease, "_table_exists", lambda *_: True)
    monkeypatch.setattr(walk_lease, "marker", lambda *_: "%s")
    monkeypatch.setattr(operations, "lock_plan_execution", lambda *_: execution)
    conn = SimpleNamespace(
        execute=lambda *_: SimpleNamespace(fetchone=lambda: {"id": execution["id"]})
    )
    monkeypatch.setattr(operations, "marker", lambda *_: "%s")
    return conn, execution


def test_active_command_plan_is_recognized_as_leaseholder(owned_plan):
    conn, execution = owned_plan
    assert (
        operations.operation_mission(
            conn,
            lease_id=8,
            project="yoke",
            actor=SimpleNamespace(actor_id="1", session_id="owner"),
        )
        is execution
    )


@pytest.mark.parametrize("session,actor", [("other", "1"), ("owner", "2")])
def test_foreign_command_plan_names_actual_leaseholder(owned_plan, session, actor):
    conn, _ = owned_plan
    with pytest.raises(operations.MachineQaProtocolError) as error:
        operations.operation_mission(
            conn,
            lease_id=8,
            project="yoke",
            actor=SimpleNamespace(actor_id=actor, session_id=session),
        )
    text = str(error.value)
    assert "you do not hold the lease on linux-lab" in text
    assert "session owner holds it for plan plan-execution" in text
    assert "Declare method_config.os or OS slots" in text


def test_non_command_active_plan_cannot_borrow_host(owned_plan):
    conn, execution = owned_plan
    execution["roster"][0]["runner_id"] = "agent_mission"
    with pytest.raises(
        operations.MachineQaProtocolError, match="active declared-host Command"
    ):
        operations.operation_mission(
            conn,
            lease_id=8,
            project="yoke",
            actor=SimpleNamespace(actor_id="1", session_id="owner"),
        )


@pytest.mark.parametrize("state", ["ready", "waiting"])
def test_command_uses_existing_plan_case_admission(monkeypatch, state):
    calls = []

    def dispatch(function_id, **kwargs):
        calls.append((function_id, kwargs))
        return {
            "state": state,
            "execution": {
                "lease_id": 8,
                "project": "yoke",
                "settings": {"resource_name": "linux-lab"},
            },
        }

    monkeypatch.setattr(commands, "_dispatch", dispatch)
    monkeypatch.setattr(commands, "reset_command_host", calls.append)
    result = commands.begin_command_host(
        {"requirement_id": 1, "runner_id": "worktree_run", "method_config": {"os": "linux"}},
        execution_id="plan-execution",
        ordinal=0,
        target="subject",
        actor="owner",
    )
    assert calls[0][0] == "test_machine.plan_case.begin"
    # The case names no host; the server selects one by OS or keeps the lease.
    assert "test_machine" not in calls[0][1]["payload"]
    if state == "waiting":
        assert result["case_outcome"] == "waiting"
    else:
        assert result is None


def _contract(monkeypatch, baselines, reach):
    from yoke_core.domain import machine_qa_execution_contract as contracts
    from yoke_core.domain import machine_qa_local_execution as local
    from yoke_core.domain import machine_qa_host_control as host_control

    contract = SimpleNamespace(
        baselines=baselines, project="yoke", settings={"resource_name": "linux-lab"}
    )
    monkeypatch.setattr(
        contracts.HostControlExecutionContract,
        "model_validate",
        classmethod(lambda cls, raw: contract),
    )
    registered = []
    monkeypatch.setattr(
        host_control,
        "register_test_machine_host_control",
        lambda: registered.append(True),
    )

    def execution(_):
        # The real factory refuses an unregistered host_control runner.
        assert registered, "host_control runner is not registered"
        return SimpleNamespace(reach_baseline=reach)

    monkeypatch.setattr(local, "_execution", execution)


@pytest.mark.parametrize("baselines", [[], ["shell-preconfigured"]])
def test_command_resets_only_the_baseline_it_declares(monkeypatch, baselines):
    reached = []
    ok = SimpleNamespace(ok=True, error_code=None, evidence={})
    _contract(monkeypatch, baselines, lambda name: reached.append(name) or ok)
    commands.reset_command_host({})
    assert reached == baselines


def test_command_reset_failure_refuses_with_recovery(monkeypatch):
    failed = SimpleNamespace(ok=False, error_code="baseline_failed", evidence={})
    _contract(monkeypatch, ["fresh-host"], lambda _: failed)
    with pytest.raises(commands.MachinePlanCaseDispatchError) as refusal:
        commands.reset_command_host({})
    assert "could not reset linux-lab to 'fresh-host'" in str(refusal.value)
    assert "yoke test-machine verify" in str(refusal.value)


def test_command_watcher_heartbeats_plan_at_interval(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(commands.time, "monotonic", lambda: now[0])
    calls = []
    pump = commands.CommandPlanLiveness(lambda: calls.append("heartbeat"))
    pump.tick()
    assert not calls
    now[0] = 60
    pump.tick()
    assert calls == ["heartbeat"]
    pump.tick()
    assert calls == ["heartbeat"]


@pytest.mark.parametrize("baselines", [("fresh-host",), ("shell-preconfigured",)])
@pytest.mark.parametrize("operation", ["reset", "screenshot"])
def test_declared_command_acquires_lease_and_can_begin_nested_operation(
    test_db, tmp_path, monkeypatch, operation, baselines
):
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from runtime.api.domain.agent_mission_qa_test_support import ACTOR, _request
    from runtime.api.domain.mission_machine_operations_test_support import begin
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
    from yoke_core.domain.qa_plan_attachments import (
        attach_plan_to_item,
        materialize_for_item,
    )
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
    from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

    configure_test_machine(test_db, tmp_path, monkeypatch)
    plan = create_plan(test_db, project="yoke", slug="command-host")
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": "command-host",
                "position": 1,
                "method_id": "command",
                "instructions": "Run a leased host operation.",
                "expected_outcome": "Pass.",
                "method_config": {"os": "macos", "command": "true"},
                "host_baselines": list(baselines),
            }
        ],
    )
    item_id = 4902
    insert_item(
        test_db,
        id=item_id,
        title="Leased command",
        workflow_id="issue",
        status="implementing",
    )
    attach_plan_to_item(
        test_db,
        plan_id=plan["id"],
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    requirement = materialize_for_item(
        test_db, item_id=item_id, transition_id="reviewing-implementation"
    )["created_requirement_ids"][0]
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    admitted = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=str(execution["id"]),
            requirement_id=requirement,
            ordinal=0,
        )
    )
    assert admitted.primary_success, admitted.error
    assert admitted.result_payload["state"] == "ready"
    # Admission names the declared baseline, so the Command resets it first.
    assert admitted.result_payload["execution"]["baselines"] == list(baselines)
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.qa_case_host_custody import case_host_lease_id
    from yoke_core.domain.qa_plan_execution_state import select_plan_execution

    current = select_plan_execution(test_db, str(execution["id"]), lock=False)
    lease_id = case_host_lease_id(test_db, current, current["roster"][0])
    assert lease_id == admitted.result_payload["execution"]["lease_id"]
    leased = get_claim(test_db, lease_id).target.test_machine
    assert admitted.result_payload["execution"]["settings"]["resource_name"] == leased
    nested = begin(operation)
    assert nested.primary_success, nested.error


OWNER = SimpleNamespace(actor_id="1", session_id="owner")


@pytest.mark.parametrize("runner", ["host_control", "agent_mission"])
def test_machine_case_plan_borrows_its_lease_to_refresh_the_golden(owned_plan, runner):
    conn, execution = owned_plan
    execution["roster"][0]["runner_id"] = runner
    execution["roster"][0]["method_config"] = {"os": "linux"}
    borrowed = operations.operation_mission(
        conn,
        lease_id=8,
        project="yoke",
        actor=OWNER,
        operation="golden_capture",
        plan_execution_id="plan-execution",
    )
    assert borrowed is execution


@pytest.mark.parametrize(
    "operation,plan_execution_id",
    [
        ("golden_capture", None),
        ("golden_capture", "another-plan"),
        ("reset", "plan-execution"),
    ],
)
def test_machine_case_lease_lends_only_the_named_golden_refresh(
    owned_plan, operation, plan_execution_id
):
    conn, execution = owned_plan
    execution["roster"][0]["runner_id"] = "host_control"
    with pytest.raises(
        operations.MachineQaProtocolError, match="mission_operation_unavailable"
    ):
        operations.operation_mission(
            conn,
            lease_id=8,
            project="yoke",
            actor=OWNER,
            operation=operation,
            plan_execution_id=plan_execution_id,
        )


def test_golden_refresh_refuses_when_the_plan_holds_no_lease(monkeypatch):
    monkeypatch.setattr(
        operations,
        "load_test_machine_contract",
        lambda *_, **__: SimpleNamespace(settings={"resource_name": "linux-lab"}),
    )
    monkeypatch.setattr(operations, "active_claim", lambda *_: None)
    with pytest.raises(
        operations.MachineQaProtocolError, match="plan_golden_refresh_lease_missing"
    ):
        operations.begin_operation_execution(
            None,
            actor=OWNER,
            project="yoke",
            test_machine="linux-lab",
            plan_execution_id="plan-execution",
            operation="golden_capture",
        )
