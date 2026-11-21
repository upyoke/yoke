"""The last lease stops only a cloud Test Machine that Yoke started."""

from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.deploy_remote_test_support import FakeRunner
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import MACHINE, _execution_wait, _notices
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain import cloud_machine_power, machine_idle_stop
from yoke_core.domain.coordination_claims import acquire, active_claim, get_claim, release
from yoke_core.domain.deploy_remote import CommandResult
from yoke_core.domain.handlers.machine_power_ownership import handle_lease
from yoke_core.domain.machine_idle_notice import collect_released_hosts, released_cloud_machines
from yoke_core.domain.qa_host_holdover import HOLDOVER_REASON, session_holdovers
from yoke_core.domain.work_claim_targets import make_qa_admission_target
from yoke_core.domain.yoke_function_dispatch import dispatch


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
        "INSERT INTO test_machines(name,settings,created_at,yoke_started_at,power_project_id) "
        "VALUES(%s,'{}',now(),CASE WHEN %s THEN now() END,1)",
        (MACHINE, marked),
    )
    test_db.commit()
    target = make_qa_admission_target(MACHINE)
    held = acquire(test_db, target, "owner")
    with collect_released_hosts() as hosts:
        release(test_db, held.id, "completed")
    assert hosts == {MACHINE}
    assert released_cloud_machines(hosts) == (
        [{"test_machine": MACHINE, "power_project": "yoke"}] if marked else []
    )


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


def test_releasing_an_idle_stop_lease_does_not_restore_a_holdover(test_db):
    seed_qa_session(test_db, "owner")
    test_db.execute(
        "INSERT INTO test_machines(name,settings,created_at) VALUES(%s,'{}',now())",
        (MACHINE,),
    )
    test_db.commit()
    target = make_qa_admission_target(MACHINE)
    request = FunctionCallRequest(
        function="test_machine.lease_acquire",
        actor=ActorContext(actor_id="1", session_id="owner"),
        target=TargetRef(kind="global"),
        payload={"test_machine": MACHINE},
    )
    direct = handle_lease(request)
    assert direct.primary_success, direct.error
    release(test_db, direct.result_payload["claim_id"], "test-machine exec complete")
    holdover = active_claim(test_db, target)
    assert holdover.reason == HOLDOVER_REASON

    idle_stop = handle_lease(
        request.model_copy(update={"payload": {"test_machine": MACHINE, "purpose": "idle-stop"}})
    )
    assert idle_stop.primary_success, idle_stop.error
    assert idle_stop.result_payload["claim_id"] == holdover.id
    release(test_db, holdover.id, "cloud Test Machine stop settled")

    assert active_claim(test_db, target) is None
    assert session_holdovers(test_db, "owner") == []


@pytest.mark.parametrize("purpose", [None, "idle-stop"])
def test_projectless_session_releases_test_machine_lease_through_dispatch(test_db, purpose):
    session_id = "projectless-lease-holder"
    seed_qa_session(test_db, session_id)
    test_db.execute(
        "UPDATE harness_sessions SET project_id=NULL, org_id=1 WHERE session_id=%s",
        (session_id,),
    )
    test_db.execute(
        "INSERT INTO test_machines(name,settings,created_at) VALUES(%s,'{}',now())",
        (MACHINE,),
    )
    test_db.commit()
    actor = ActorContext(actor_id="1", session_id=session_id)
    target = TargetRef(kind="global")

    acquired = dispatch(
        FunctionCallRequest(
            function="test_machine.lease_acquire",
            actor=actor,
            target=target,
            payload={"test_machine": MACHINE, "purpose": purpose},
        ),
        ambient_session_id=session_id,
    )
    assert acquired.success, acquired.error
    claim_id = acquired.result["claim_id"]
    released = dispatch(
        FunctionCallRequest(
            function="claims.coordination_claim.release",
            actor=actor,
            target=target,
            payload={"claim_id": claim_id, "reason": "finished"},
        ),
        ambient_session_id=session_id,
    )
    assert released.success, released.error
    assert get_claim(test_db, claim_id).released_at is not None
    if purpose == "idle-stop":
        assert active_claim(test_db, make_qa_admission_target(MACHINE)) is None


@pytest.mark.parametrize("marker, confirmed", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("provider", ["aws", "azure"])
def test_client_rechecks_marker_under_lease_and_clears_only_on_confirmed_stop(
    monkeypatch, marker, confirmed, provider
):
    steps = []
    notices = []
    project = "power-owner"
    vm_group_id = "/subscriptions/sub/resourceGroups/lab"
    nic_id = "/subscriptions/sub/resourceGroups/network-lab/providers/Microsoft.Network/networkInterfaces/nic"
    ip_id = f"{vm_group_id}/providers/Microsoft.Network/publicIPAddresses/vm-yoke-power"
    outcome = CommandResult(0, "", "") if confirmed else CommandResult(1, "", "provider denied")

    def data(value):
        return CommandResult(0, json.dumps(value), "")

    if provider == "aws":
        instance_id = "i-001"
        runner = FakeRunner([data(["running"]), outcome, outcome])
        expected_actions = ["describe-instances", "stop-instances", "wait"]
        stop_command = f"yoke aws exec --project {project} -- ec2 stop-instances --instance-ids {instance_id}"
    else:
        instance_id = f"{vm_group_id}/providers/Microsoft.Compute/virtualMachines/vm"
        deallocated = data({
            "powerState": "VM deallocated",
            "location": "eastus",
            "networkProfile": {"networkInterfaces": [{"id": nic_id}]},
        })
        nic = data({"ipConfigurations": [{
            "id": f"{nic_id}/ipConfigurations/primary",
            "publicIPAddress": {"id": ip_id},
        }]})
        ips = data([{"id": ip_id.upper()}, {"id": ip_id.replace("vm-yoke-power", "other")}])
        runner = FakeRunner([
            data({"powerState": "VM running"}), outcome, deallocated,
            deallocated, nic, outcome, ips, outcome,
        ])
        expected_actions = ["show", "deallocate", "show", "show", "nic", "nic", "public-ip", "public-ip"]
        stop_command = f"yoke azure exec --project {project} -- vm deallocate --ids {instance_id}"

    @contextmanager
    def azure_session(*args, **kwargs):
        yield ("az",), {}

    def call(function, payload):
        steps.append((function, payload))
        if function == "projects.capability_settings.get":
            return {"settings_json": json.dumps({"subscription_id": "sub"})}
        return {
            "yoke_started": marker,
            "power_project": project,
            "settings": {
                "resource_name": MACHINE,
                "cloud_instance_id": instance_id,
                "cloud_provider": provider,
            },
        }

    def record_dispatch(function, payload):
        steps.append((function, payload))
        return SimpleNamespace(success=True, result={"claim_id": 7})

    monkeypatch.setattr(cloud_machine_power, "_aws_env", lambda _project: {})
    monkeypatch.setattr(cloud_machine_power, "azure_session", azure_session)
    monkeypatch.setattr(cloud_machine_power, "_dispatch", record_dispatch)
    monkeypatch.setattr(cloud_machine_power, "_call", call)
    machine_idle_stop.stop_released(
        [{"power_project": project, "test_machine": MACHINE}],
        runner=runner,
        emit=notices.append,
    )
    assert steps[0] == (
        "test_machine.lease_acquire", {"test_machine": MACHINE, "purpose": "idle-stop"}
    )
    expected = ["test_machine.lease_acquire", "test_machine.get"]
    if marker and provider == "azure":
        expected.append("projects.capability_settings.get")
    if confirmed:
        expected.append("test_machine.power_stopped")
        assert ("test_machine.power_stopped", {"test_machine": MACHINE}) in steps
    assert [function for function, _ in steps] == [*expected, "claims.coordination_claim.release"]

    actions = [call["argv"][2] for call in runner.calls]
    if not marker:
        assert actions == []
    elif not confirmed:
        assert actions == expected_actions[:2]
        assert any(stop_command in line for line in notices)
    else:
        assert actions == expected_actions
        if provider == "azure":
            assert runner.calls[5]["argv"] == [
                "az", "network", "nic", "ip-config", "update",
                "--resource-group", "network-lab", "--nic-name", "nic",
                "--name", "primary", "--public-ip-address", "null", "--output", "json",
            ]
            assert runner.calls[-1]["argv"] == [
                "az", "network", "public-ip", "delete", "--ids", ip_id, "--output", "json",
            ]
        else:
            assert "instance-stopped" in runner.calls[-1]["argv"]
