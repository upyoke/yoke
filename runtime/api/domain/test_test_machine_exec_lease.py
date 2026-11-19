"""`yoke test-machine exec` holds the host's lease and powers a stopped cloud machine on."""

from __future__ import annotations

import subprocess
from datetime import timedelta
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.domain.agent_mission_host_access_test_support import (
    DRIVER,
    mission as mission,
)
from runtime.api.domain.agent_mission_qa_test_support import ACTOR
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.handlers.machine_power_ownership import (
    handle_lease_execution_heartbeat,
)
from yoke_core.domain.qa_plan_execution_authority import PLAN_EXECUTION_STALE_SECONDS
from yoke_core.domain.qa_plan_execution_lifecycle import reap_stale_plan_executions
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

    def __init__(
        self, lease: dict[str, Any] | None = None, name: str = "linux-lab"
    ) -> None:
        self.lease = lease
        self.name = name
        self.running = False
        self.events: list[str] = []

    def dispatch(self, **kw: Any) -> FunctionCallResponse:
        name = kw["function_id"]
        self.events.append(name)
        result: dict[str, Any] = {}
        if name == "test_machine.get":
            result = {
                "test_machine": self.name,
                "settings": {**SETTINGS, "resource_name": self.name},
                "active_lease": self.lease,
            }
        elif name == "test_machine.lease_acquire":
            assert kw["payload"]["test_machine"] == self.name
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
    def install(
        lease: dict[str, Any] | None = None,
        name: str = "linux-lab",
        actor: Any = SimpleNamespace(session_id="mine"),
        host: type[FakeCloudMachine] = FakeCloudMachine,
    ) -> FakeCloudMachine:
        fake = host(lease, name)
        monkeypatch.setattr(adapter, "ensure_handlers_loaded", lambda: None)
        monkeypatch.setattr(adapter, "build_actor", lambda session_id=None: actor)
        monkeypatch.setattr(adapter.machine_config, "yoke_home", lambda: Path(tmp_path))
        monkeypatch.setattr(adapter, "call_dispatcher", fake.dispatch)
        monkeypatch.setattr(custody, "call_dispatcher", fake.dispatch)
        monkeypatch.setattr(cloud_machine_power, "power_on", fake.power_on)
        monkeypatch.setattr(
            "yoke_harness.test_machine_remote_exec.run_remote_command", fake.run
        )
        return fake

    return install


def _exec(*argv: str, name: str = "linux-lab") -> int:
    return adapter.test_machine_exec(["--test-machine", name, "--", *argv])


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
        "test_machine.get",
    ]
    assert fake.lease is None and fake.running


def test_exec_takes_its_own_holdover_so_its_release_renews_it(machine) -> None:
    fake = machine({"session_id": "mine", "holdover_expires_at": "2026-11-19T01:02:00Z"})

    assert _exec("true") == 0

    assert fake.events == [
        "test_machine.get",
        "test_machine.lease_acquire",
        "power_on",
        "ran",
        "claims.coordination_claim.release",
        "test_machine.get",
    ]


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

    assert fake.events == [
        "test_machine.get",
        "test_machine.lease_execution_heartbeat",
        "power_on",
        "ran",
        "test_machine.lease_execution_heartbeat",
    ]
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
    assert fake.events[-2:] == ["claims.coordination_claim.release", "test_machine.get"]


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
        "yoke_core.domain.machine_qa_host_rows.test_machine_rows",
        lambda conn: [SimpleNamespace(
            project="example", test_machine=SETTINGS["resource_name"], settings=SETTINGS,
        )],
    )
    monkeypatch.setattr(cloud_machine_power, "machine_power", reject_provider_call)

    response = yoke_function_dispatch.dispatch(request)

    assert active_claim(test_db, target) is None
    assert response.model_dump() == expected.model_dump()
    assert settle_response(response).model_dump() == expected.model_dump()


class WalkHost(FakeCloudMachine):
    """The walk's retained host: heartbeat calls reach the real server handler."""

    def dispatch(self, **kw: Any) -> FunctionCallResponse:
        if kw["function_id"] != "test_machine.lease_execution_heartbeat":
            return super().dispatch(**kw)
        self.events.append(kw["function_id"])
        outcome = handle_lease_execution_heartbeat(
            FunctionCallRequest(
                function=kw["function_id"],
                actor=kw["actor"],
                target=kw["target"],
                payload=kw["payload"],
            )
        )
        assert outcome.primary_success, outcome.error
        return FunctionCallResponse(
            success=True, function=kw["function_id"], version="v1",
            result=outcome.result_payload,
        )


@pytest.fixture
def walk(test_db, mission, machine, monkeypatch):
    """Exec on the caller's walking mission host, reaching the real handler."""
    _, execution = mission
    test_db.commit()

    def install(lease: dict[str, Any] | None) -> FakeCloudMachine:
        return machine(lease, name=DRIVER, actor=ACTOR, host=WalkHost)

    return execution, install


def _walk_row(conn, execution_id: str) -> tuple[str, Any]:
    row = conn.execute(
        "SELECT state, heartbeat_at FROM qa_plan_executions WHERE id=%s",
        (execution_id,),
    ).fetchone()
    return str(row[0]), row[1]


def _backdate(conn, execution_id: str) -> Any:
    conn.execute(
        "UPDATE qa_plan_executions SET heartbeat_at=%s WHERE id=%s",
        (utc_now() - timedelta(seconds=PLAN_EXECUTION_STALE_SECONDS + 60), execution_id),
    )
    conn.commit()
    return _walk_row(conn, execution_id)[1]


def test_exec_borrowing_a_walks_lease_keeps_that_walk_alive(test_db, walk) -> None:
    execution, install = walk
    assert _walk_row(test_db, execution["id"])[0] == "walking"
    stale = _backdate(test_db, execution["id"])

    host = install({"session_id": ACTOR.session_id})
    assert _exec("true", name=DRIVER) == 0

    state, beat = _walk_row(test_db, execution["id"])
    assert state == "walking" and beat > stale
    assert host.events.count("test_machine.lease_execution_heartbeat") == 2
    reap_stale_plan_executions(test_db)
    assert _walk_row(test_db, execution["id"])[0] == "walking"


@pytest.mark.parametrize("change", ["acquired", "waiting", "completed", "other-session"])
def test_exec_outside_the_callers_walk_heartbeats_nothing(test_db, walk, change) -> None:
    execution, install = walk
    if change in {"waiting", "completed"}:
        test_db.execute(
            "UPDATE qa_plan_executions SET state=%s WHERE id=%s", (change, execution["id"])
        )
    if change == "other-session":
        test_db.execute(
            "UPDATE qa_plan_executions SET session_id='another-session' WHERE id=%s",
            (execution["id"],),
        )
    before = _backdate(test_db, execution["id"])
    host = install(None if change == "acquired" else {"session_id": ACTOR.session_id})

    assert _exec("true", name=DRIVER) == 0

    assert _walk_row(test_db, execution["id"])[1] == before
    assert ("test_machine.lease_execution_heartbeat" in host.events) is (
        change != "acquired"
    )
