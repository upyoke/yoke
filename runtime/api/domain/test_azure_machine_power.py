"""Faked Azure CLI proof for start, rebinding and last-lease deallocation."""

from __future__ import annotations

from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from yoke_core.domain import cloud_machine_power as power
from yoke_core.domain.cloud_machine_power_stop import stop_released
from yoke_core.domain.azure_instance_power import AzureMachinePower
from yoke_core.domain.deploy_remote import CommandResult
from yoke_contracts.azure_admin import AzureAdminError
from yoke_contracts.machine_config.test_machine import (
    validate_test_machine_settings,
    TestMachineCapabilityError as CapabilityError,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.api.function_call import FunctionCallResponse
from runtime.api.domain.deploy_remote_test_support import FakeRunner

ID = "/subscriptions/sub/resourceGroups/lab/providers/Microsoft.Compute/virtualMachines/vm"
SETTINGS = {
    "resource_name": "azure-lab",
    "host": "192.0.2.1",
    "user": "test",
    "os": "linux",
    "operating_notes": "",
    "cloud_provider": "azure",
    "cloud_instance_id": ID,
}
OK = CommandResult(0, "", "")


def details(state="VM running", address=SETTINGS["host"]):
    return CommandResult(0, json.dumps({"powerState": state, "publicIps": address}), "")


@pytest.fixture
def controller(monkeypatch):
    calls = []

    def dispatch(fn, payload):
        calls.append((fn, payload))
        result = {"settings": SETTINGS, "settings_token": "cas"}
        if fn == "projects.capability_settings.get":
            result = {"settings_json": json.dumps({"subscription_id": "sub"})}
        if fn == "claims.coordination_claim.acquire_if_free":
            result = {"claim": {"id": 1}}
        return FunctionCallResponse(
            success=True, function=fn, version="v1", result=result
        )

    @contextmanager
    def session(project, settings, **kwargs):
        yield "az", {"AZURE_CONFIG_DIR": "private-test-cache"}

    monkeypatch.setattr(power, "_dispatch", dispatch)
    monkeypatch.setattr(power, "azure_session", session)
    monkeypatch.setattr(
        power, "wait_for_ssh_login", lambda *a, **kw: calls.append(("ssh", a[1]))
    )
    return calls


def test_start_rebinds_current_public_ip_before_login(controller):
    runner = FakeRunner(
        [details("VM deallocated"), OK, details(), details(address="192.0.2.2")]
    )
    result = power.power_on("project", SETTINGS, runner=runner, emit=lambda _: None)
    assert result["host"] == "192.0.2.2"
    assert [call["argv"][2] for call in runner.calls] == [
        "show",
        "start",
        "show",
        "show",
    ]
    assert [fn for fn, _ in controller][-2:] == ["test_machine.host_rebind", "ssh"]
    assert controller[-1][1]["host"] == result["host"]
    assert all(
        call["env"]["AZURE_CONFIG_DIR"] == "private-test-cache" for call in runner.calls
    )


def test_running_azure_machine_refreshes_address_without_start_or_login(controller):
    runner = FakeRunner([details(), details()])
    assert (
        power.power_on("project", SETTINGS, runner=runner, emit=lambda _: None)
        == SETTINGS
    )
    assert [call["argv"][2] for call in runner.calls] == ["show", "show"]
    assert not any(fn == "ssh" for fn, _ in controller)


def test_last_release_deallocates_a_stopped_but_allocated_vm(controller):
    runner = FakeRunner([details("VM stopped"), OK])
    stop_released(
        [{"project": "project", "test_machine": "azure-lab"}],
        runner=runner,
        emit=lambda _: None,
    )
    assert [call["argv"][2] for call in runner.calls] == ["show", "deallocate"]
    assert controller[-1][0] == "claims.coordination_claim.release"


def test_no_public_ip_refuses_before_ssh(controller):
    with pytest.raises(HostControlLocalError) as error:
        power.power_on(
            "project",
            SETTINGS,
            runner=FakeRunner([details(), details(address="")]),
            emit=lambda _: None,
        )
    assert error.value.code == "test_machine_power_no_public_address"
    assert "yoke azure exec" in error.value.recovery_hint
    assert not any(fn == "ssh" for fn, _ in controller)


def test_failed_start_names_azure_recovery(controller):
    with pytest.raises(HostControlLocalError) as error:
        power.power_on(
            "project",
            SETTINGS,
            runner=FakeRunner([details("VM stopped"), CommandResult(1, "", "Denied")]),
            emit=lambda _: None,
        )
    assert "Denied" in str(error.value)
    assert "azure exec" in error.value.recovery_hint


def test_waits_for_an_inflight_deallocation_before_start():
    runner = FakeRunner(
        [
            details("VM deallocating"),
            details("VM deallocated"),
            OK,
            details(),
            details(),
        ]
    )
    provider = AzureMachinePower(runner, "az", {}, ID, "project", lambda _: None)
    assert provider.start() == "VM deallocating"
    assert provider.address() == SETTINGS["host"]


def test_power_transition_timeout_names_recovery():
    runner = FakeRunner([details("VM starting")])
    clock = iter([0, 601])
    provider = AzureMachinePower(
        runner, "az", {}, ID, "project", lambda _: None, clock=lambda: next(clock)
    )
    with pytest.raises(AzureAdminError, match="600s.*azure exec"):
        provider.start()


def test_azure_settings_require_full_resource_id():
    assert validate_test_machine_settings(SETTINGS)["cloud_instance_id"] == ID
    for changed in (
        {"cloud_provider": "gcp"},
        {"cloud_instance_id": "i-123"},
        {"cloud_instance_id": ID + "/bad"},
    ):
        with pytest.raises(CapabilityError):
            validate_test_machine_settings({**SETTINGS, **changed})


def test_release_notice_includes_azure_and_aws_without_touching_cloud(monkeypatch):
    from contextlib import nullcontext
    from yoke_core.domain import cloud_machine_release_notice as notice

    rows = [
        SimpleNamespace(project="project", test_machine="azure-lab", settings=SETTINGS),
        SimpleNamespace(
            project="project",
            test_machine="aws-lab",
            settings={"cloud_instance_id": "i-1"},
        ),
    ]
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect", lambda: nullcontext(None)
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_capability_rows.test_machine_capability_rows",
        lambda _: rows,
    )
    assert notice.released_cloud_machines({"azure-lab", "aws-lab"}) == [
        {"project": "project", "test_machine": name}
        for name in ("azure-lab", "aws-lab")
    ]


def test_fleet_report_names_cloud_provider(monkeypatch):
    from yoke_core.domain import steering_fleet_report_test_machines as fleet

    monkeypatch.setattr(fleet, "_table_exists", lambda *a: True)
    rows = [
        ("test-machine:azure-lab", json.dumps(SETTINGS)),
        (
            "test-machine:aws-lab",
            json.dumps({"os": "linux", "cloud_instance_id": "i-1"}),
        ),
    ]
    conn = SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchall=lambda: rows))
    lines = fleet.test_machine_lines(fleet.read_test_machines(conn, 1))
    assert "azure-lab (OS: linux · azure)" in lines[0]
    assert "aws-lab (OS: linux · aws)" in lines[0]
