"""Cloud Test Machines start for a lease and stop when no lease holds them."""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain import test_machine_power
from yoke_core.domain.deploy_remote import CommandResult
from yoke_core.domain.test_machine_power import (
    power_off_released,
    power_on,
    wait_for_ssh_login,
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


@pytest.fixture(autouse=True)
def powered(monkeypatch):
    """Each test starts with no machine recorded as powered by this process."""
    monkeypatch.setattr(test_machine_power, "_powered", {})


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setattr(test_machine_power, "_aws_env", lambda project: {"P": project})


def test_machine_without_instance_id_is_never_touched(monkeypatch):
    monkeypatch.setattr(
        test_machine_power, "_aws_env", lambda project: pytest.fail("no AWS call")
    )
    runner = FakeRunner()
    power_on("yoke", MAC, runner=runner)
    assert runner.calls == []


def test_stopped_machine_starts_then_waits_for_an_ssh_login(monkeypatch, aws):
    waited = []
    monkeypatch.setattr(
        test_machine_power,
        "wait_for_ssh_login",
        lambda project, settings, emit, runner: waited.append(
            (project, settings["resource_name"])
        ),
    )
    runner = FakeRunner([_json(["stopped"]), OK, OK])
    power_on("yoke", CLOUD, runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == ["describe-instances", "start-instances", "wait"]
    assert waited == [("yoke", "windows-lab")]


def test_running_machine_skips_the_ssh_wait(monkeypatch, aws):
    monkeypatch.setattr(
        test_machine_power, "wait_for_ssh_login", lambda *a, **k: pytest.fail("no wait")
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


class _LoginRunner:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls: list[list[str]] = []

    def run(self, argv, *, timeout, **_kwargs):
        self.calls.append(list(argv))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def ssh_key(monkeypatch, tmp_path):
    key = tmp_path / "ssh_private_key"
    key.write_text("key", encoding="utf-8")
    monkeypatch.setattr(
        test_machine_power, "machine_capability_secret_path", lambda *a: key
    )
    return key


def test_ssh_wait_retries_logins_until_one_succeeds(ssh_key):
    runner = _LoginRunner(
        [
            CommandResult(255, "", "Connection refused"),
            subprocess.TimeoutExpired("ssh", 60),
            OK,
        ]
    )
    sleeps: list[float] = []
    wait_for_ssh_login(
        "yoke", CLOUD, lambda _l: None, runner=runner, sleeper=sleeps.append
    )
    assert len(runner.calls) == 3 and len(sleeps) == 2
    assert runner.calls[0][:3] == ["ssh", "-i", str(ssh_key)]
    assert runner.calls[0][-2:] == ["Administrator@54.0.0.1", "exit"]


def test_ssh_wait_timeout_refuses_with_the_last_error(ssh_key):
    clock = iter([0.0, 0.0, 700.0])
    runner = _LoginRunner([CommandResult(255, "", "No route to host")])
    with pytest.raises(HostControlLocalError) as exc:
        wait_for_ssh_login(
            "yoke",
            CLOUD,
            lambda _l: None,
            runner=runner,
            sleeper=lambda _s: None,
            clock=lambda: next(clock),
        )
    assert exc.value.code == "test_machine_power_ssh_unreachable"
    assert "No route to host" in str(exc.value)


def test_ssh_wait_without_the_machine_key_leaves_the_refusal_to_host_control(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        test_machine_power,
        "machine_capability_secret_path",
        lambda *a: tmp_path / "missing",
    )
    runner = _LoginRunner([])
    wait_for_ssh_login("yoke", CLOUD, lambda _l: None, runner=runner)
    assert runner.calls == []


@pytest.fixture
def leases(monkeypatch, aws):
    """Active lease per machine as test_machine.get reports it."""
    held: dict[str, dict | None] = {}

    def call(function_id, payload):
        assert function_id == "test_machine.get" and payload["project"] == "yoke"
        return {"active_lease": held.get(payload["test_machine"])}

    monkeypatch.setattr(test_machine_power, "_call", call)
    return held


def _lease_cloud_machine(runner: FakeRunner) -> None:
    power_on("yoke", CLOUD, runner=runner, emit=lambda _l: None)


def test_last_release_stops_the_machine_this_process_powered(leases):
    runner = FakeRunner([_json(["running"]), _json(["running"]), _json(["54.0.0.1"]), OK])
    _lease_cloud_machine(runner)
    power_off_released(runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == [
        "describe-instances",
        "describe-instances",
        "describe-addresses",
        "stop-instances",
    ]
    assert test_machine_power._powered == {}


def test_another_lease_keeps_the_machine_running(leases):
    leases["windows-lab"] = {"id": 7}
    runner = FakeRunner([_json(["running"])])
    _lease_cloud_machine(runner)
    power_off_released(runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == ["describe-instances"]


def test_machines_without_instance_id_are_never_stopped(leases):
    runner = FakeRunner()
    power_on("yoke", MAC, runner=runner)
    power_off_released(runner=runner, emit=lambda _l: None)
    assert runner.calls == []


def test_already_stopped_machine_gets_no_stop(leases):
    runner = FakeRunner([_json(["running"]), _json(["stopped"])])
    _lease_cloud_machine(runner)
    power_off_released(runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == ["describe-instances", "describe-instances"]


def test_machine_without_elastic_ip_stays_running_with_a_named_reason(leases):
    runner = FakeRunner([_json(["running"]), _json(["running"]), _json([])])
    _lease_cloud_machine(runner)
    lines: list[str] = []
    power_off_released(runner=runner, emit=lines.append)
    assert "stop-instances" not in _ec2_actions(runner)
    assert lines[0].startswith("test_machine_power_stop_skipped: idle Test Machine")
    assert "Recovery: declare an Elastic IP" in lines[0]


def test_stop_failure_is_reported_and_never_raised(leases):
    runner = FakeRunner(
        [
            _json(["running"]),
            _json(["running"]),
            _json(["54.0.0.1"]),
            CommandResult(1, "", "Denied"),
        ]
    )
    _lease_cloud_machine(runner)
    lines: list[str] = []
    power_off_released(runner=runner, emit=lines.append)
    assert lines[-1].startswith("test_machine_power_stop_failed:")
    assert "ec2 stop-instances --instance-ids i-1" in lines[-1]


def test_lease_read_failure_is_reported_and_never_raised(monkeypatch, aws):
    monkeypatch.setattr(test_machine_power, "_powered", {("yoke", "windows-lab"): CLOUD})

    def call(function_id, payload):
        raise ConnectionError("control plane unreachable")

    monkeypatch.setattr(test_machine_power, "_call", call)
    lines: list[str] = []
    power_off_released(emit=lines.append)
    assert lines[0].startswith("test_machine_power_stop_failed: Test Machine windows-lab")
    assert "yoke test-machine verify --project yoke --test-machine windows-lab" in lines[0]
    assert test_machine_power._powered == {}
