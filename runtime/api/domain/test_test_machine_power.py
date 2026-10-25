"""Cloud Test Machines start for a lease and stop when no lease holds them."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain import test_machine_power
from yoke_core.domain.deploy_remote import CommandResult
from yoke_core.domain.test_machine_power import (
    host_case_projects,
    power_off_idle,
    power_on,
    wait_for_ssh_server,
)
from runtime.api.domain.test_deploy_remote import FakeRunner

OK = CommandResult(0, "", "")
CLOUD = {
    "resource_name": "windows-lab",
    "host": "54.0.0.1",
    "user": "Administrator",
    "os": "windows",
    "cloud_instance_id": "i-1",
}
MAC = {"resource_name": "mac-lab", "host": "10.0.0.2", "user": "qa", "os": "macos"}


def _json(value) -> CommandResult:
    return CommandResult(0, json.dumps(value), "")


def _ec2_actions(runner: FakeRunner) -> list[str]:
    return [call["argv"][2] for call in runner.calls]


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setattr(test_machine_power, "_aws_env", lambda project: {"P": project})


@pytest.fixture
def fleet(monkeypatch, aws):
    machines: list[dict] = []

    def call(function_id, payload):
        assert (function_id, payload) == ("test_machine.list", {"project": "yoke"})
        return {"test_machines": machines}

    monkeypatch.setattr(test_machine_power, "_call", call)
    return machines


def test_machine_without_instance_id_is_never_touched(monkeypatch):
    monkeypatch.setattr(
        test_machine_power, "_aws_env", lambda project: pytest.fail("no AWS call")
    )
    runner = FakeRunner()
    power_on("yoke", MAC, runner=runner)
    assert runner.calls == []


def test_stopped_machine_starts_then_waits_for_its_ssh_server(monkeypatch, aws):
    waited = []
    monkeypatch.setattr(
        test_machine_power,
        "wait_for_ssh_server",
        lambda name, host, emit: waited.append((name, host)),
    )
    runner = FakeRunner([_json(["stopped"]), OK, OK])
    power_on("yoke", CLOUD, runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == ["describe-instances", "start-instances", "wait"]
    assert waited == [("windows-lab", "54.0.0.1")]


def test_running_machine_skips_the_ssh_wait(monkeypatch, aws):
    monkeypatch.setattr(
        test_machine_power, "wait_for_ssh_server", lambda *a: pytest.fail("no wait")
    )
    runner = FakeRunner([_json(["running"])])
    power_on("yoke", CLOUD, runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == ["describe-instances"]


def test_start_failure_refuses_with_named_code_and_recovery(aws):
    runner = FakeRunner([_json(["stopped"]), CommandResult(1, "", "Denied")])
    with pytest.raises(HostControlLocalError) as exc:
        power_on("yoke", CLOUD, runner=runner, emit=lambda _l: None)
    assert exc.value.code == "test_machine_power_start_failed"
    assert "windows-lab" in str(exc.value) and "Denied" in str(exc.value)
    assert "describe-instances --instance-ids i-1" in exc.value.recovery_hint


class _Socket:
    def __init__(self, banner: bytes):
        self.banner = banner

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def recv(self, _size):
        return self.banner


def test_ssh_wait_retries_until_the_server_sends_its_banner():
    answers = [OSError("Connection refused"), _Socket(b""), _Socket(b"SSH-2.0-OpenSSH")]

    def connect(address, timeout):
        assert address == ("54.0.0.1", 22)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    sleeps = []
    wait_for_ssh_server(
        "windows-lab", "54.0.0.1", lambda _l: None, connect=connect, sleeper=sleeps.append
    )
    assert answers == [] and len(sleeps) == 2


def test_ssh_wait_timeout_refuses_with_the_last_error():
    clock = iter([0.0, 0.0, 400.0])

    def connect(address, timeout):
        raise OSError("No route to host")

    with pytest.raises(HostControlLocalError) as exc:
        wait_for_ssh_server(
            "windows-lab",
            "54.0.0.1",
            lambda _l: None,
            connect=connect,
            sleeper=lambda _s: None,
            clock=lambda: next(clock),
        )
    assert exc.value.code == "test_machine_power_ssh_unreachable"
    assert "No route to host" in str(exc.value)


def test_last_release_stops_an_idle_running_machine(fleet):
    fleet.append({"settings": CLOUD, "active_lease": None})
    runner = FakeRunner([_json(["running"]), _json(["54.0.0.1"]), OK])
    power_off_idle("yoke", runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == [
        "describe-instances",
        "describe-addresses",
        "stop-instances",
    ]


def test_another_lease_keeps_the_machine_running(fleet):
    fleet.append({"settings": CLOUD, "active_lease": {"id": 7}})
    runner = FakeRunner()
    power_off_idle("yoke", runner=runner, emit=lambda _l: None)
    assert runner.calls == []


def test_machines_without_instance_id_are_not_swept(fleet):
    fleet.append({"settings": MAC, "active_lease": None})
    runner = FakeRunner()
    power_off_idle("yoke", runner=runner, emit=lambda _l: None)
    assert runner.calls == []


def test_already_stopped_machine_gets_no_stop(fleet):
    fleet.append({"settings": CLOUD, "active_lease": None})
    runner = FakeRunner([_json(["stopped"])])
    power_off_idle("yoke", runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == ["describe-instances"]


def test_machine_without_elastic_ip_stays_running_with_a_named_reason(fleet):
    fleet.append({"settings": CLOUD, "active_lease": None})
    runner = FakeRunner([_json(["running"]), _json([])])
    lines: list[str] = []
    power_off_idle("yoke", runner=runner, emit=lines.append)
    assert _ec2_actions(runner) == ["describe-instances", "describe-addresses"]
    assert lines[0].startswith("test_machine_power_stop_skipped: idle Test Machine")
    assert "Recovery: declare an Elastic IP" in lines[0]


def test_stop_failure_is_reported_and_never_raised(fleet):
    fleet.append({"settings": CLOUD, "active_lease": None})
    runner = FakeRunner([_json(["running"]), _json(["54.0.0.1"]), CommandResult(1, "", "Denied")])
    lines: list[str] = []
    power_off_idle("yoke", runner=runner, emit=lines.append)
    assert lines[-1].startswith("test_machine_power_stop_failed:")
    assert "ec2 stop-instances --instance-ids i-1" in lines[-1]


def test_sweep_failure_is_reported_and_never_raised(monkeypatch):
    def call(function_id, payload):
        raise ConnectionError("control plane unreachable")

    monkeypatch.setattr(test_machine_power, "_call", call)
    lines: list[str] = []
    power_off_idle("yoke", emit=lines.append)
    assert lines[0].startswith("test_machine_power_sweep_failed:")
    assert "control plane unreachable" in lines[0]


def test_no_selected_project_sweeps_nothing(monkeypatch):
    monkeypatch.setattr(test_machine_power, "_call", lambda *a: pytest.fail("no read"))
    power_off_idle(None)


def test_plan_sweep_covers_only_projects_with_host_cases():
    cases = [
        {"project": "yoke", "runner_id": "host_control"},
        {"project": "acme", "runner_id": "agent_mission"},
        {"project": "beta", "runner_id": "worktree_run", "method_config": {"test_machine": "m"}},
        {"project": "gamma", "runner_id": "worktree_run", "method_config": {}},
    ]
    assert host_case_projects(cases) == ["acme", "beta", "yoke"]
