"""`yoke test-machine exec` holds the host's lease and powers a stopped cloud machine on."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_cli.commands import test_machine_desktop_lease as custody
from yoke_cli.commands.adapters import test_machine_exec as adapter
from yoke_core.domain import cloud_machine_power

SETTINGS = {
    "host": "linux-lab.example.ts.net",
    "user": "qa",
    "os": "linux",
    "cloud_instance_id": "i-0abc",
    "resource_name": "linux-lab",
}


class FakeCloudMachine:
    """A cloud machine that is stopped unless a lease holds it."""

    def __init__(self, lease: dict[str, Any] | None = None) -> None:
        self.lease = lease
        self.running = False
        self.events: list[str] = []

    def dispatch(self, **kw: Any) -> FunctionCallResponse:
        name = kw["function_id"]
        self.events.append(name)
        result: dict[str, Any] = {}
        if name == "test_machine.get":
            result = {
                "test_machine": "linux-lab",
                "settings": SETTINGS,
                "active_lease": self.lease,
            }
        elif name == "claims.coordination_claim.acquire_if_free":
            assert kw["payload"]["key"] == "QA_HOST:linux-lab"
            assert kw["payload"]["reason"] == "test-machine exec"
            self.lease = {"session_id": kw["actor"].session_id}
            result = {"claim": {"id": 41}}
        elif name == "claims.coordination_claim.release":
            assert kw["payload"]["claim_id"] == 41
            # Stop-on-last-release: the transport stops a host left free.
            self.lease, self.running = None, False
            self.events.append("stopped")
        return FunctionCallResponse(
            success=True, function=name, version="v1", result=result
        )

    def power_on(self, project: str, settings: dict[str, str]) -> None:
        assert self.lease is not None, "powered on without a lease"
        assert settings["cloud_instance_id"] == "i-0abc"
        self.running = True
        self.events.append("power_on")

    def run(self, **kw: Any) -> subprocess.CompletedProcess:
        assert self.running, "ran on a stopped machine"
        self.events.append("ran")
        return subprocess.CompletedProcess([], 0, "", "")


@pytest.fixture
def machine(monkeypatch, tmp_path):
    def install(lease: dict[str, Any] | None = None) -> FakeCloudMachine:
        fake = FakeCloudMachine(lease)
        monkeypatch.setattr(adapter, "ensure_handlers_loaded", lambda: None)
        monkeypatch.setattr(
            adapter,
            "build_actor",
            lambda session_id=None: SimpleNamespace(session_id="mine"),
        )
        monkeypatch.setattr(adapter.machine_config, "yoke_home", lambda: Path(tmp_path))
        monkeypatch.setattr(adapter, "call_dispatcher", fake.dispatch)
        monkeypatch.setattr(custody, "call_dispatcher", fake.dispatch)
        monkeypatch.setattr(cloud_machine_power, "power_on", fake.power_on)
        monkeypatch.setattr(
            "yoke_harness.test_machine_remote_exec.run_remote_command", fake.run
        )
        return fake

    return install


def _exec(*argv: str) -> int:
    return adapter.test_machine_exec(
        ["--project", "yoke", "--test-machine", "linux-lab", "--", *argv]
    )


def test_exec_on_a_stopped_unleased_machine_leases_powers_on_runs_and_releases(
    machine,
) -> None:
    fake = machine()

    assert _exec("true") == 0

    assert fake.events == [
        "test_machine.get",
        "claims.coordination_claim.acquire_if_free",
        "power_on",
        "ran",
        "claims.coordination_claim.release",
        "stopped",
    ]
    assert fake.lease is None and not fake.running


def test_exec_while_another_session_holds_the_lease_refuses_untouched(
    machine, capsys
) -> None:
    fake = machine({"session_id": "theirs", "item": {"ref": "QA-9"}})

    assert _exec("true") == 1

    assert "test_machine_leased" in capsys.readouterr().err
    assert fake.events == ["test_machine.get"]


def test_exec_borrows_the_callers_own_lease_and_leaves_it_held(machine) -> None:
    fake = machine({"session_id": "mine"})

    assert _exec("true") == 0

    assert fake.events == ["test_machine.get", "power_on", "ran"]
    assert fake.lease == {"session_id": "mine"}


def test_a_failed_power_on_refuses_by_name_and_still_releases(
    machine, monkeypatch, capsys
) -> None:
    fake = machine()

    def fail(*_: Any) -> None:
        raise RuntimeError("cloud unavailable")

    monkeypatch.setattr(cloud_machine_power, "power_on", fail)

    assert _exec("true") == 1

    err = capsys.readouterr().err
    assert "host_control_local_execution_failed" in err
    assert "phase=lease_power_on" in err
    assert "ran" not in fake.events
    assert fake.events[-2:] == ["claims.coordination_claim.release", "stopped"]
