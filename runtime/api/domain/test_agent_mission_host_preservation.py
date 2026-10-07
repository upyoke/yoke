"""Mission preparation keeps the host; the walk resets only a declared baseline."""

from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_core.domain import machine_qa_local_execution as local
from yoke_core.domain import machine_qa_mission_walk as walk
from yoke_core.domain.machine_qa_method_contracts import (
    MachineQaExecutionError,
    validate_machine_method_config,
)
from yoke_harness import qa_host_package_fixture


@pytest.fixture
def mission(monkeypatch):
    control = FakeHostControl()
    control.os = "linux"
    control.files[control.home + "/browser-profile"] = "operator-session"
    contract = SimpleNamespace(
        baselines=[],
        continues_execution_id=None,
        cases=[SimpleNamespace(host_baseline=None, method_config={})],
        plan_execution_id="mission-preserve-home",
        lease_id=1,
        contract_digest="digest",
    )
    resets = []
    packages = []

    def reach_baseline(name):
        resets.append(name)
        control.files.clear()
        return SimpleNamespace(name=name, ok=True, error_code=None, evidence={})

    execution = SimpleNamespace(
        control=control,
        material=SimpleNamespace(secrets={}),
        reach_baseline=reach_baseline,
    )
    monkeypatch.setattr(local, "_mission_contract", lambda raw: contract)
    monkeypatch.setattr(local, "_execution", lambda contract, **kwargs: execution)
    monkeypatch.setattr(walk, "_mission_contract", lambda raw: contract)
    monkeypatch.setattr(walk, "_execution", lambda contract, **kwargs: execution)
    monkeypatch.setattr(
        qa_host_package_fixture,
        "restore_host_packages",
        lambda control, declared, **kwargs: (
            packages.append(("restore", declared)) or {"ok": True}
        ),
    )
    monkeypatch.setattr(
        qa_host_package_fixture,
        "record_host_packages",
        lambda control: packages.append(("record", None)) or {"ok": True},
    )
    return contract, control, resets, packages


def test_empty_baseline_preserves_home_and_package_state(mission):
    _, control, resets, packages = mission
    before = dict(control.files)
    prepared = local.prepare_agent_mission_contract({})["preparation"]
    result = local.execute_agent_mission_host_command(
        {}, argv=["/usr/bin/true"], gui_session=False, timeout_seconds=60
    )
    assert prepared["baseline"] is None
    assert prepared["ok"] is True
    assert prepared["scratch_path"].startswith("/tmp/")
    assert result["exit_code"] == 0
    assert control.files == before
    assert resets == packages == []
    assert result["os_packages"] == {}


@pytest.mark.parametrize("baseline", ["fresh-host", "shell-preconfigured"])
def test_explicit_baseline_resets_at_walk_start_not_at_plan_time(mission, baseline):
    contract, _, resets, packages = mission
    contract.baselines = [baseline]
    contract.cases[0].host_baseline = baseline
    planned = local.prepare_agent_mission_contract({})["preparation"]
    assert planned["baseline"] is None
    assert resets == []
    walked = walk.execute_agent_mission_walk_start({})["preparation"]
    assert walked["baseline"] == baseline
    assert resets == [baseline]
    assert packages == [("restore", None), ("restore", None)]


def test_explicit_package_fixture_preserves_home_but_restores_packages(mission):
    contract, control, resets, packages = mission
    state = {"os_packages": {"present": ["tmux"]}}
    contract.cases[0].method_config = {"host_starting_state": state}
    before = dict(control.files)
    local.prepare_agent_mission_contract({})
    assert control.files == before
    assert resets == []
    assert packages == [("restore", state)]


def test_continuation_does_not_restore_but_keeps_declared_package_journal(mission):
    contract, _, resets, packages = mission
    contract.continues_execution_id = "previous-mission"
    contract.cases[0].host_baseline = "fresh-host"
    local.prepare_agent_mission_contract({})
    local.execute_agent_mission_host_command(
        {}, argv=["/usr/bin/true"], gui_session=False, timeout_seconds=60
    )
    assert resets == []
    assert packages == [("record", None)]


@pytest.mark.parametrize("machine", ["linux-lab", "test-mac"])
def test_machine_pin_is_retained_by_the_execution_validator(machine):
    config = {"machine": machine, "assertions": [{"argv": ["/usr/bin/true"]}]}
    result = validate_machine_method_config(
        "machine-state-check", config, entry_surface=None, required_completion=None
    )
    assert result["machine"] == machine
    assert result["assertions"] == [{"argv": ["/usr/bin/true"], "expected_exit": 0}]
    assert config["machine"] == machine


@pytest.mark.parametrize("machine", ["../escape", "", "invalid machine"])
def test_invalid_machine_pin_is_refused(machine):
    with pytest.raises(MachineQaExecutionError, match="valid registered Test Machine"):
        validate_machine_method_config(
            "machine-state-check",
            {"machine": machine, "assertions": [{"argv": ["/usr/bin/true"]}]},
            entry_surface=None,
            required_completion=None,
        )
