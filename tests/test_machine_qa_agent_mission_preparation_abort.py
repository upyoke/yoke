"""A cancelled mission preparation settles its blocking call, then restores.

Feedback 98859: the abort reached the runner during a blocking native
baseline call. The call must finish, the next phase boundary must stop
preparation, and the docket must carry the declared baseline's restore.
"""

from types import SimpleNamespace

import pytest

from yoke_core.domain import agent_mission_preparation as preparation_module
from yoke_core.domain import machine_qa_local_execution as local
from yoke_core.domain import machine_qa_plan_case_execution as client
from yoke_harness import qa_host_package_fixture


def _contract(baseline, method_config=None):
    return SimpleNamespace(
        baselines=[baseline] if baseline else [],
        continues_execution_id=None,
        cases=[SimpleNamespace(host_baseline=baseline, method_config=method_config or {})],
        plan_execution_id="cancelled-mission",
        lease_id=7,
        contract_digest="digest",
        settings={"resource_name": "lab-2"},
    )


@pytest.fixture
def host(monkeypatch):
    state = {"abort": False, "abort_in": None, "reached": [], "calls": []}

    def reach(name):
        state["reached"].append(name)
        if state["abort_in"] == "baseline":
            state["abort"] = True  # Cancellation lands during the blocking call.
        return SimpleNamespace(name=name, ok=True, error_code=None, evidence={})

    def disk():
        state["calls"].append("disk")
        return {"ok": True}

    def packages(*args, **kwargs):
        state["calls"].append("packages")
        if state["abort_in"] == "packages":
            state["abort"] = True
        return {}

    execution = SimpleNamespace(
        control=SimpleNamespace(
            mission_scratch_path=lambda execution_id: f"/tmp/{execution_id}",
            require_mission_disk_space=disk,
        ),
        material=SimpleNamespace(secrets={}),
        reach_baseline=reach,
    )
    monkeypatch.setattr(local, "_execution", lambda *a, **k: execution)
    monkeypatch.setattr(qa_host_package_fixture, "restore_host_packages", packages)
    state["beat"] = lambda: {"abort_requested": state["abort"]}
    return state


def _prepare(monkeypatch, host, contract):
    monkeypatch.setattr(local, "_mission_contract", lambda raw: contract)
    return local.prepare_agent_mission_contract({}, progress_callback=host["beat"])


def test_abort_during_blocking_baseline_reuses_its_proof(monkeypatch, host):
    host["abort_in"] = "baseline"
    payload = _prepare(monkeypatch, host, _contract("fresh-host"))
    preparation = payload["preparation"]
    evidence = preparation["evidence"]
    assert preparation["ok"] is False
    assert preparation["error_code"] == "qa_host_abort_requested"
    assert evidence["baseline_outcome"]["state"] == "completed"
    assert evidence["starting_state_restore"]["restored"] is True
    assert evidence["starting_state_restore"]["baseline"] == "fresh-host"
    assert evidence["abort"]["host_work_stopped"] is True
    assert host["reached"] == ["fresh-host"]  # The settled call is the restore.
    assert host["calls"] == []  # No later phase ran after cancellation.


def test_abort_before_the_baseline_restores_the_declared_one(monkeypatch, host):
    host["abort"] = True
    payload = _prepare(monkeypatch, host, _contract("fresh-host"))
    evidence = payload["preparation"]["evidence"]
    assert evidence["baseline_outcome"]["state"] == "not_started"
    assert evidence["starting_state_restore"]["restored"] is True
    assert host["reached"] == ["fresh-host"]


def test_abort_after_package_restore_restores_the_baseline_again(monkeypatch, host):
    host["abort_in"] = "packages"
    contract = _contract("fresh-host", {"host_starting_state": {"packages": []}})
    payload = _prepare(monkeypatch, host, contract)
    evidence = payload["preparation"]["evidence"]
    assert host["calls"] == ["disk", "packages"]
    assert host["reached"] == ["fresh-host", "fresh-host"]
    assert evidence["starting_state_restore"]["restored"] is True


def test_abort_without_a_declared_baseline_records_no_restore_needed(
    monkeypatch, host
):
    host["abort"] = True
    payload = _prepare(monkeypatch, host, _contract(None))
    restore = payload["preparation"]["evidence"]["starting_state_restore"]
    assert restore == {"baseline": None, "restoration_required": False}
    assert host["reached"] == []


def test_uncancelled_preparation_is_unchanged(monkeypatch, host):
    payload = _prepare(monkeypatch, host, _contract("fresh-host"))
    preparation = payload["preparation"]
    assert preparation["ok"] is True
    assert "starting_state_restore" not in preparation["evidence"]
    assert host["calls"] == ["disk", "packages"]


def test_runner_stops_after_submitting_a_cancelled_docket(monkeypatch):
    prepared = {
        "lease_id": 7,
        "contract_digest": "digest",
        "preparation": {
            "ok": False,
            "error_code": "qa_host_abort_requested",
            "evidence": {"starting_state_restore": {"restored": True}},
        },
    }
    dispatched = []

    def dispatch(function, **kwargs):
        dispatched.append(function)
        if function == "test_machine.mission.ready":
            return {"result": {"requirement_id": 5}}
        return {}

    monkeypatch.setattr(
        client, "_begin", lambda *a: {"state": "ready", "execution": {"lease_id": 7}}
    )
    monkeypatch.setattr(client, "_report_selection", lambda *a: None)
    monkeypatch.setattr(client, "refreshed_case_contract", lambda execution, **k: execution)
    monkeypatch.setattr(client, "_dispatch", dispatch)
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_host_control.register_test_machine_host_control",
        lambda: None,
    )
    monkeypatch.setattr(local, "prepare_agent_mission_contract", lambda *a, **k: prepared)
    with pytest.raises(client.MachinePlanCaseDispatchError, match="qa_host_abort_requested"):
        client.execute_plan_agent_mission_case(
            {"requirement_id": 5, "public_ref": "YOK-1"},
            execution_id="cancelled-mission",
            ordinal=0,
            actor=SimpleNamespace(actor_id="1", session_id="s"),
        )
    assert dispatched == ["test_machine.mission.ready"]
    assert preparation_module.ABORT_ERROR_CODE == "qa_host_abort_requested"
