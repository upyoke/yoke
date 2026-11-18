"""Faked Azure CLI proof for start, disposable public IPs."""

from __future__ import annotations

from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from yoke_core.domain import cloud_machine_power as power
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


pytestmark = pytest.mark.windows

ID = "/subscriptions/sub/resourceGroups/lab/providers/Microsoft.Compute/virtualMachines/vm"
SETTINGS = {
    "resource_name": "azure-lab",
    "host": "azure-lab.example.ts.net",
    "user": "test",
    "os": "linux",
    "operating_notes": "",
    "cloud_provider": "azure",
    "cloud_instance_id": ID,
}
OK = CommandResult(0, "", "")


NIC_ID = "/subscriptions/sub/resourceGroups/lab/providers/Microsoft.Network/networkInterfaces/nic"
IP_ID = "/subscriptions/sub/resourceGroups/lab/providers/Microsoft.Network/publicIPAddresses/vm-yoke-power"
CONFIG_ID = NIC_ID + "/ipConfigurations/primary"


def data(value):
    return CommandResult(0, json.dumps(value), "")


def details(state="VM running"):
    return data(
        {
            "powerState": state,
            "location": "eastus",
            "networkProfile": {
                "networkInterfaces": [{"id": NIC_ID}],
            },
        }
    )


def nic(attached=False):
    return data(
        {
            "ipConfigurations": [
                {
                    "id": CONFIG_ID,
                    "publicIPAddress": {
                        "id": IP_ID,
                    }
                    if attached
                    else None,
                }
            ]
        }
    )


@pytest.fixture
def controller(monkeypatch):
    calls = []

    def dispatch(fn, payload):
        calls.append((fn, payload))
        result = {"settings": SETTINGS, "settings_token": "cas"}
        if fn == "projects.capability_settings.get":
            result = {"settings_json": json.dumps({"subscription_id": "sub"})}
        return FunctionCallResponse(
            success=True, function=fn, version="v1", result=result
        )

    @contextmanager
    def session(project, settings, **kwargs):
        yield ("az",), {"AZURE_CONFIG_DIR": "private-test-cache"}

    monkeypatch.setattr(power, "_dispatch", dispatch)
    monkeypatch.setattr(power, "azure_session", session)
    monkeypatch.setattr(
        power, "wait_for_ssh_login", lambda *a, **kw: calls.append(("ssh", a[1]))
    )
    return calls


def test_start_attaches_disposable_ip_and_keeps_magicdns(controller):
    runner = FakeRunner(
        [details("VM deallocated"), details(), nic(), OK, OK, OK, details()]
    )
    assert (
        power.power_on("project", SETTINGS, runner=runner, emit=lambda _: None) is None
    )
    actions = [call["argv"][1:3] for call in runner.calls]
    assert actions == [
        ["vm", "show"],
        ["vm", "show"],
        ["network", "nic"],
        ["network", "public-ip"],
        ["network", "nic"],
        ["vm", "start"],
        ["vm", "show"],
    ]
    assert "Standard" in runner.calls[3]["argv"]
    assert IP_ID in runner.calls[4]["argv"]
    assert [fn for fn, _ in controller] == ["projects.capability_settings.get", "ssh"]
    assert controller[-1][1]["host"] == SETTINGS["host"]
    assert all(
        call["env"]["AZURE_CONFIG_DIR"] == "private-test-cache" for call in runner.calls
    )


def test_running_azure_machine_keeps_existing_power_ip_without_start_or_login(
    controller,
):
    runner = FakeRunner([details(), details(), nic(True)])
    assert (
        power.power_on("project", SETTINGS, runner=runner, emit=lambda _: None) is None
    )
    assert not any(fn == "ssh" for fn, _ in controller)
    assert not any("start" in call["argv"] for call in runner.calls)


def test_failed_start_names_azure_recovery(controller):
    runner = FakeRunner(
        [
            details("VM stopped"),
            details(),
            nic(),
            OK,
            OK,
            CommandResult(1, "", "Denied"),
        ]
    )
    with pytest.raises(HostControlLocalError) as error:
        power.power_on("project", SETTINGS, runner=runner, emit=lambda _: None)
    assert "Denied" in str(error.value)
    assert "azure exec" in error.value.recovery_hint


def test_waits_for_an_inflight_deallocation_before_start():
    runner = FakeRunner(
        [
            details("VM deallocating"),
            details("VM deallocated"),
            details(),
            nic(),
            OK,
            OK,
            OK,
            details(),
        ]
    )
    provider = AzureMachinePower(runner, ("az",), {}, ID, "project", lambda _: None)
    assert provider.start() == "VM deallocating"
    assert runner.calls[6]["argv"][1:3] == ["vm", "start"]


def test_unmanaged_static_ip_names_rollout_recovery():
    runner = FakeRunner(
        [
            details(),
            data(
                {
                    "ipConfigurations": [
                        {"id": CONFIG_ID, "publicIPAddress": {"id": "permanent"}}
                    ]
                }
            ),
        ]
    )
    provider = AzureMachinePower(runner, ("az",), {}, ID, "project", lambda _: None)
    with pytest.raises(
        AzureAdminError, match="unmanaged public IP.*operator exception"
    ):
        provider._attach_public_ip()


def test_power_transition_timeout_names_recovery():
    runner = FakeRunner([details("VM starting"), details(), nic(True)])
    clock = iter([0, 601])
    provider = AzureMachinePower(
        runner, ("az",), {}, ID, "project", lambda _: None, clock=lambda: next(clock)
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


@pytest.mark.parametrize("instance_id", [ID, ID.lower(), ID.upper()])
def test_power_accepts_resource_id_casing_allowed_by_settings(instance_id):
    runner = FakeRunner([details(), details(), nic(), OK, OK])
    provider = AzureMachinePower(
        runner, ("az",), {}, instance_id, "project", lambda _: None
    )
    assert provider.public_ip_id.lower() == IP_ID.lower()
    assert provider.start() == "running"
    create = runner.calls[3]["argv"]
    assert create[create.index("--resource-group") + 1].lower() == "lab"
