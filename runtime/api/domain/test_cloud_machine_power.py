"""Cloud Test Machines start for a lease and wait until a login works."""

from __future__ import annotations

from runtime.api.domain.cloud_machine_power_test_support import (
    CLOUD as CLOUD,
    MAC as MAC,
    OK as OK,
)


import base64
import json
import re
import subprocess

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain import cloud_machine_power
from yoke_core.domain.deploy_remote import CommandResult
from yoke_core.domain.cloud_machine_power import (
    power_on,
    wait_for_ssh_login,
)
from runtime.api.domain.deploy_remote_test_support import FakeRunner


pytestmark = pytest.mark.windows


def _json(value) -> CommandResult:
    return CommandResult(0, json.dumps(value), "")


def _ec2_actions(runner: FakeRunner) -> list[str]:
    return [call["argv"][2] for call in runner.calls]


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setattr(cloud_machine_power, "_aws_env", lambda project: {"P": project})
    monkeypatch.setattr(
        cloud_machine_power, "_call",
        lambda function, _payload: {"power_project": "yoke", "settings": CLOUD}
        if function == "test_machine.get" else {},
    )


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
    runner = FakeRunner([_json(["stopped"]), OK, OK])
    power_on("yoke", CLOUD, runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == [
        "describe-instances",
        "start-instances",
        "wait",
    ]
    assert waited == [("yoke", "windows-lab")]


def test_running_machine_skips_the_ssh_wait(monkeypatch, aws):
    monkeypatch.setattr(
        cloud_machine_power,
        "wait_for_ssh_login",
        lambda *a, **k: pytest.fail("no wait"),
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
        self.inputs: list[str | None] = []
        self.timeouts: list[float] = []

    def run(self, argv, *, timeout, input_text=None, **_kwargs):
        self.calls.append(list(argv))
        self.inputs.append(input_text)
        self.timeouts.append(timeout)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def ssh_key(monkeypatch, tmp_path):
    key = tmp_path / "ssh_private_key"
    key.write_text("key", encoding="utf-8")
    monkeypatch.setattr(
        cloud_machine_power, "test_machine_secret_path", lambda *a: key
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
    clock = iter([0.0, 0.0, 700.0, 700.0])
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
        "test_machine_secret_path",
        lambda *a: tmp_path / "missing",
    )
    runner = _LoginRunner([])
    wait_for_ssh_login("yoke", CLOUD, lambda _l: None, runner=runner)
    assert runner.calls == []


def test_power_keeps_magicdns_host_without_public_address_read(
    monkeypatch, aws, ssh_key
):
    monkeypatch.setattr(
        cloud_machine_power, "_dispatch", lambda *a: pytest.fail("no dispatch")
    )
    settings = {**CLOUD, "host": "lab.example.ts.net"}
    runner = FakeRunner([_json(["stopped"]), OK, OK, OK])
    assert power_on("yoke", settings, runner=runner, emit=lambda _: None) is None
    assert settings["host"] == "lab.example.ts.net"
    assert _ec2_actions(runner)[:3] == ["describe-instances", "start-instances", "wait"]
    assert len(runner.calls) == 4 and runner.calls[-1]["argv"][0] == "ssh"
    assert runner.calls[-1]["argv"][-2] == "Administrator@lab.example.ts.net"
    assert "PublicIpAddress" not in str(runner.calls)


NATIVE = {**CLOUD, "os": "windows", "user": r"LAB\yokeqa"}
MISSING = CommandResult(3, "", "windows_console_session_missing")


class _Clock:
    now = 0.0

    def read(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_native_windows_ssh_readiness_does_not_invoke_wsl(ssh_key):
    runner = _LoginRunner([OK])
    wait_for_ssh_login("yoke", NATIVE, lambda _: None, runner=runner)
    command = runner.calls[0][-1]
    assert command.startswith("powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand ")
    script = base64.b64decode(command.split()[-1]).decode("utf-16-le")
    assert "$testUser='yokeqa'" in script
    assert "quser.exe" in script and "'console'" in script and "Get-Process explorer" in script
    assert "No User exists for *') {\n    Refuse-MissingConsole" in script
    assert {
        "AutoAdminLogon", "DefaultUserName", "DefaultDomainName",
    } == set(re.findall(r"\.GetValue\('([^']+)'", script))
    assert "DefaultPassword" not in script
    assert "GetValueNames() -contains 'AutoLogonCount'" in script
    assert "Get-LocalUser -Name $testUser" in script and "IsAccountLocked" in script
    assert "if ($auto -eq '0')" in script and "Automatic sign-in is off." in script
    assert not any(verb in script.lower() for verb in ("cim", "wmi", "add-type", "wsl", "'active'"))
    assert runner.inputs == [None]


def test_native_windows_waits_for_console_after_ssh(ssh_key):
    clock = _Clock()
    runner = _LoginRunner([MISSING, MISSING, OK])
    output = []

    wait_for_ssh_login("yoke", NATIVE, output.append, runner=runner, clock=clock.read, sleeper=clock.sleep)

    assert len(runner.calls) == 3
    assert len(output) == 3
    assert "console session" in output[0]
    assert "accepts SSH logins" in output[1]
    assert "signed in at its console after 20.0s" in output[2]


def test_native_windows_missing_console_warns_and_leaves_ssh_available(ssh_key):
    clock = _Clock()
    diagnostics = (
        "AutoAdminLogon=0, DefaultUserName=yokeqa, DefaultDomainName=LAB, AutoLogonCountPresent=False",
        "Automatic sign-in is off. Rerun desktop provisioning, which validates the stored password.",
        "AccountEnabled=True, AccountLocked=False",
    )
    last = CommandResult(3, "", "\n".join((MISSING.stderr, *diagnostics)))
    runner = _LoginRunner([MISSING, MISSING, last])
    output = []

    wait_for_ssh_login(
        "yoke", NATIVE, output.append, runner=runner,
        timeout_s=25, clock=clock.read, sleeper=clock.sleep,
    )

    assert clock.now == 25.0
    assert runner.timeouts == [25, 15, 5]
    assert output[-1].startswith("windows_console_session_missing: Test Machine")
    assert "within 25s" in output[-1]
    assert "rerun Windows desktop provisioning" in output[-1]
    assert all(detail in output[-1] for detail in diagnostics)
    assert output[-1].count("windows_console_session_missing") == 1


@pytest.mark.parametrize("failure", [
    CommandResult(255, "", "Connection refused"),
    CommandResult(1, "", "quser: Access is denied"),
])
def test_native_windows_other_failures_remain_ssh_unavailable(ssh_key, failure):
    clock = _Clock()
    runner = _LoginRunner([failure])
    output = []

    with pytest.raises(HostControlLocalError) as exc:
        wait_for_ssh_login(
            "yoke", NATIVE, output.append, runner=runner,
            timeout_s=5, clock=clock.read, sleeper=clock.sleep,
        )

    assert exc.value.code == "ssh_unavailable"
    assert exc.value.phase == "power"
    assert failure.stderr in str(exc.value)
    assert len(output) == 1
    assert clock.now == 5.0
