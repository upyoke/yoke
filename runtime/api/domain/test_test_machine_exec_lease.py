"""`yoke test-machine exec` holds the host's lease and powers a stopped cloud machine on."""

from __future__ import annotations

import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_cli.transport.settled_response import settle_response
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_cli.commands import test_machine_desktop_lease as custody
from yoke_cli.commands.adapters import test_machine_exec as adapter
from yoke_core.domain import cloud_machine_power, yoke_function_dispatch
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.work_claim_targets import make_qa_admission_target

SETTINGS = {
    "host": "linux-lab.example.ts.net",
    "user": "qa",
    "os": "linux",
    "cloud_instance_id": "i-0abc",
    "resource_name": "linux-lab",
}


class FakeCloudMachine:
    """A cloud machine that starts stopped and stays running after release."""

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
        elif name == "test_machine.lease_acquire":
            assert kw["payload"]["test_machine"] == "linux-lab"
            self.lease = {"session_id": kw["actor"].session_id}
            result = {"claim_id": 41}
        elif name == "claims.coordination_claim.release":
            assert kw["payload"]["claim_id"] == 41
            self.lease = None
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
        ["--test-machine", "linux-lab", "--", *argv]
    )


def test_exec_on_a_stopped_unleased_machine_leases_powers_on_runs_and_releases(
    machine,
) -> None:
    fake = machine()

    assert _exec("true") == 0

    assert fake.events == [
        "test_machine.get",
        "test_machine.lease_acquire",
        "power_on",
        "ran",
        "claims.coordination_claim.release",
    ]
    assert fake.lease is None and fake.running


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
    assert fake.events[-1] == "claims.coordination_claim.release"


def test_release_frees_cloud_host_without_power_data_or_provider_calls(
    test_db, monkeypatch,
) -> None:
    owner = "owner"
    seed_qa_session(test_db, owner)
    target = make_qa_admission_target(SETTINGS["resource_name"])
    held = acquire(test_db, target, owner)
    request = FunctionCallRequest(
        function="claims.coordination_claim.release",
        actor=ActorContext(actor_id="1", session_id=owner),
        target=TargetRef(kind="global"),
        payload={"claim_id": held.id, "reason": "complete"},
    )
    expected = FunctionCallResponse(
        success=True, function=request.function, version="v1",
        result={"claim": {"id": held.id}},
    )

    def release_lease(call, **kwargs):
        release(test_db, call.payload["claim_id"], call.payload["reason"])
        return expected

    def reject_provider_call(*args, **kwargs):
        pytest.fail("lease release called the cloud provider")

    monkeypatch.setattr(yoke_function_dispatch, "_dispatch_impl", release_lease)
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect", lambda: nullcontext(test_db)
    )
    monkeypatch.setattr(
        "yoke_core.domain.test_machine_rows.test_machine_rows",
        lambda conn: [SimpleNamespace(
            project="example", test_machine=SETTINGS["resource_name"], settings=SETTINGS,
        )],
    )
    monkeypatch.setattr(cloud_machine_power, "machine_power", reject_provider_call)

    response = yoke_function_dispatch.dispatch(request)

    assert active_claim(test_db, target) is None
    assert response.model_dump() == expected.model_dump()
    assert settle_response(response).model_dump() == expected.model_dump()
