"""Cloud Test Machines start for a lease and wait until a login works."""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain import cloud_machine_power
from yoke_core.domain.deploy_remote import CommandResult
from yoke_core.domain.cloud_machine_power import (
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


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setattr(cloud_machine_power, "_aws_env", lambda project: {"P": project})


def test_machine_without_instance_id_is_never_touched(monkeypatch):
    monkeypatch.setattr(
        cloud_machine_power, "_aws_env", lambda project: pytest.fail("no AWS call")
    )
    runner = FakeRunner()
    power_on("yoke", MAC, runner=runner)
    assert runner.calls == []


def test_stopped_machine_starts_then_waits_for_an_ssh_login(monkeypatch, aws):
    waited = []
    monkeypatch.setattr(
        cloud_machine_power,
        "wait_for_ssh_login",
        lambda project, settings, emit, runner: waited.append(
            (project, settings["resource_name"])
        ),
    )
    runner = FakeRunner([_json(["stopped"]), OK, OK, _json([CLOUD["host"]])])
    power_on("yoke", CLOUD, runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == [
        "describe-instances",
        "start-instances",
        "wait",
        "describe-instances",
    ]
    assert waited == [("yoke", "windows-lab")]


def test_running_machine_skips_the_ssh_wait(monkeypatch, aws):
    monkeypatch.setattr(
        cloud_machine_power,
        "wait_for_ssh_login",
        lambda *a, **k: pytest.fail("no wait"),
    )
    runner = FakeRunner([_json(["running"]), _json([CLOUD["host"]])])
    power_on("yoke", CLOUD, runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == ["describe-instances", "describe-instances"]


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
        self.inputs: list[str | None] = []

    def run(self, argv, *, timeout, input_text=None, **_kwargs):
        self.calls.append(list(argv))
        self.inputs.append(input_text)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def ssh_key(monkeypatch, tmp_path):
    key = tmp_path / "ssh_private_key"
    key.write_text("key", encoding="utf-8")
    monkeypatch.setattr(
        cloud_machine_power, "machine_capability_secret_path", lambda *a: key
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
    assert runner.calls[0][-2] == "Administrator@54.0.0.1"
    assert runner.calls[0][-1].startswith("powershell.exe ")
    assert runner.inputs[0].splitlines()[0]  # the framed WSL Python probe


def test_ssh_wait_on_a_non_windows_host_only_logs_in(ssh_key):
    runner = _LoginRunner([OK])
    wait_for_ssh_login("yoke", {**CLOUD, "os": "linux"}, lambda _l: None, runner=runner)
    assert runner.calls[0][-2:] == ["Administrator@54.0.0.1", "exit"]
    assert runner.inputs == [None]


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
    assert exc.value.code == "ssh_unavailable"
    assert "No route to host" in str(exc.value)


def test_ssh_wait_without_the_machine_key_leaves_the_refusal_to_host_control(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        cloud_machine_power,
        "machine_capability_secret_path",
        lambda *a: tmp_path / "missing",
    )
    runner = _LoginRunner([])
    wait_for_ssh_login("yoke", CLOUD, lambda _l: None, runner=runner)
    assert runner.calls == []


@pytest.mark.parametrize("stored_host", [CLOUD["host"], "184.195.162.151"])
def test_start_rebinds_before_ssh_and_preserves_other_settings(
    monkeypatch, aws, ssh_key, stored_host
):
    from yoke_contracts.api.function_call import FunctionCallResponse

    address = "184.195.162.151"
    calls = []

    def dispatch(function_id, payload):
        calls.append((function_id, payload))
        result = {"settings": {**CLOUD, "host": stored_host}, "settings_token": "token"}
        return FunctionCallResponse(
            success=True, function=function_id, version="v1", result=result
        )

    monkeypatch.setattr(cloud_machine_power, "_dispatch", dispatch)
    runner = FakeRunner([_json(["stopped"]), OK, OK, _json([address]), OK])
    returned = power_on("yoke", CLOUD, runner=runner, emit=lambda _: None)
    writes = [payload for fn, payload in calls if fn == "test_machine.host_rebind"]
    assert writes == (
        [
            {
                "project": "yoke",
                "test_machine": CLOUD["resource_name"],
                "host": address,
                "base_settings": "token",
            }
        ]
        if stored_host != address
        else []
    )
    assert returned == {**CLOUD, "host": address}
    assert runner.calls[-1]["argv"][-2] == f"Administrator@{address}"


def test_no_public_address_never_rebinds_or_probes(monkeypatch, aws):
    monkeypatch.setattr(
        cloud_machine_power, "_dispatch", lambda *a: pytest.fail("no dispatch")
    )
    runner = FakeRunner([_json(["running"]), _json([None])])
    with pytest.raises(HostControlLocalError) as refused:
        power_on("yoke", CLOUD, runner=runner, emit=lambda _: None)
    assert refused.value.code == "test_machine_power_no_public_address"
    assert refused.value.phase == "power"
    assert all(call["argv"][0] == "aws" for call in runner.calls)


def test_rebind_refusal_keeps_server_diagnosis(monkeypatch, aws):
    from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError

    monkeypatch.setattr(
        cloud_machine_power,
        "_call",
        lambda *a: {"settings": CLOUD, "settings_token": "old"},
    )
    monkeypatch.setattr(
        cloud_machine_power,
        "_dispatch",
        lambda *a: FunctionCallResponse(
            success=False,
            function="f",
            version="v1",
            error=FunctionError(
                code="function_version_skew",
                message="minimum serving version next-release",
            ),
        ),
    )
    with pytest.raises(HostControlLocalError) as refused:
        power_on(
            "yoke",
            CLOUD,
            runner=FakeRunner([_json(["running"]), _json(["184.195.162.151"])]),
        )
    assert refused.value.code == "test_machine_host_rebind_refused"
    assert "function_version_skew" in str(refused.value)
    assert "next-release" in str(refused.value)
