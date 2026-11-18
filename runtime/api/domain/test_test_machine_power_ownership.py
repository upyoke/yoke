"""The last lease stops only a cloud Test Machine that Yoke started."""

from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import MACHINE, _execution_wait, _notices
from yoke_core.domain import cloud_machine_power, machine_idle_stop
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.machine_idle_notice import collect_released_hosts
from yoke_core.domain.work_claim_targets import make_qa_admission_target


@pytest.mark.parametrize("state", ["running", "pending", "VM starting", "stopped", "VM deallocated"])
def test_only_a_start_performed_by_yoke_marks_the_host(monkeypatch, state):
    from contextlib import nullcontext

    started = []
    settings = {"resource_name": MACHINE, "cloud_instance_id": "vm-1"}

    def call(function, payload):
        if function == "test_machine.get":
            return {"power_project": "power-owner", "settings": settings}
        started.append((function, payload))
        return {}

    def power_provider(project, *_):
        assert project == "power-owner"
        return nullcontext(SimpleNamespace(read_command="provider read", start=lambda: state))

    monkeypatch.setattr(cloud_machine_power, "_call", call)
    monkeypatch.setattr(cloud_machine_power, "machine_power", power_provider)
    monkeypatch.setattr(cloud_machine_power, "wait_for_ssh_login", lambda *a, **k: None)
    cloud_machine_power.power_on("qa-project", settings)
    assert started == (
        [("test_machine.power_started", {"test_machine": MACHINE})]
        if state in {"stopped", "VM deallocated"}
        else []
    )


@pytest.mark.parametrize("marked", [True, False])
def test_last_release_emits_notice_only_for_yoke_start(test_db, marked):
    seed_qa_session(test_db, "owner")
    test_db.execute(
        "INSERT INTO test_machines(name,settings,created_at,yoke_started_at) "
        "VALUES(%s,'{}',now(),CASE WHEN %s THEN now() END)",
        (MACHINE, marked),
    )
    test_db.commit()
    target = make_qa_admission_target(MACHINE)
    held = acquire(test_db, target, "owner")
    with collect_released_hosts() as hosts:
        release(test_db, held.id, "completed")
    assert hosts == ({MACHINE} if marked else set())


def test_queue_handoff_preserves_marker_and_never_notifies_stop(test_db, monkeypatch):
    seed_qa_session(test_db, "owner", "next")
    _notices(monkeypatch)
    test_db.execute(
        "INSERT INTO test_machines(name,settings,created_at,yoke_started_at) "
        "VALUES(%s,'{}',now(),now())",
        (MACHINE,),
    )
    test_db.commit()
    target = make_qa_admission_target(MACHINE)
    held = acquire(test_db, target, "owner")
    _execution_wait(test_db, "next")
    with collect_released_hosts() as hosts:
        release(test_db, held.id, "completed")
    assert not hosts
    assert active_claim(test_db, target).session_id == "next"
    assert test_db.execute("SELECT yoke_started_at FROM test_machines WHERE name=%s", (MACHINE,)).fetchone()[0]


@pytest.mark.parametrize("marker, confirmed", [(False, False), (True, False), (True, True)])
def test_client_rechecks_marker_under_lease_and_clears_only_on_confirmed_stop(
    monkeypatch, marker, confirmed
):
    from contextlib import nullcontext

    steps = []

    def stop():
        steps.append("stop")
        if not confirmed:
            raise machine_idle_stop.Ec2InstancePowerError("not confirmed")

    def dispatch(function, payload):
        steps.append(function)
        return SimpleNamespace(success=True, result={"claim_id": 7})

    def call(function, payload):
        steps.append(function)
        return {
            "yoke_started": marker,
            "power_project": "power-owner",
            "settings": {"resource_name": MACHINE, "cloud_instance_id": "vm-1"},
        }

    provider = SimpleNamespace(read_command="provider read", stop_command="provider stop", stop=stop)
    monkeypatch.setattr(cloud_machine_power, "_dispatch", dispatch)
    monkeypatch.setattr(cloud_machine_power, "_call", call)
    monkeypatch.setattr(cloud_machine_power, "machine_power", lambda *args: nullcontext(provider))
    machine_idle_stop.stop_released(
        [{"power_project": "power-owner", "test_machine": MACHINE}], emit=lambda _line: None
    )
    expected = ["test_machine.lease_acquire", "test_machine.get"]
    if marker:
        expected.append("stop")
    if confirmed:
        expected.append("test_machine.power_stopped")
    assert steps == [*expected, "claims.coordination_claim.release"]
