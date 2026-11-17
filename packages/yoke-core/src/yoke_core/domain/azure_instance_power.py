"""Azure VM power operations; deallocation releases the compute allocation."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from yoke_contracts.azure_admin import AzureAdminError, run_checked
from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_core.domain.deploy_remote import CommandRunner


@dataclass
class AzureMachinePower:
    runner: CommandRunner
    command: tuple[str, ...]
    env: dict[str, str]
    instance_id: str
    project: str
    emit: Callable[[str], None]
    clock: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep

    @property
    def read_command(self):
        return f"yoke azure exec --project {self.project} -- vm show --ids {self.instance_id} --show-details"

    @property
    def stop_command(self):
        return f"yoke azure exec --project {self.project} -- vm deallocate --ids {self.instance_id}"

    def _run(self, action, *args, timeout=60):
        return run_checked(
            self.runner.run,
            [
                *self.command,
                "vm",
                action,
                "--ids",
                self.instance_id,
                *args,
                "--output",
                "json",
            ],
            self.env,
            action=f"vm {action}",
            timeout=timeout,
        )

    def _details(self):
        result = self._run("show", "--show-details")
        try:
            details = json.loads(result.stdout)
        except ValueError:
            raise AzureAdminError(
                "Azure vm show returned invalid JSON; retry the VM read"
            ) from None
        if not isinstance(details, dict) or not details.get("powerState"):
            raise AzureAdminError(
                "Azure vm show returned no powerState; check the resource id and retry"
            )
        return details

    def start(self):
        state = self._details()["powerState"]
        self.emit(f"  Azure VM {self.instance_id} is {state}")
        if state == "VM running":
            self._attach_public_ip()
            return "running"
        if state not in (
            "VM stopped",
            "VM deallocated",
            "VM starting",
            "VM stopping",
            "VM deallocating",
        ):
            raise AzureAdminError(
                f"Azure VM is {state}; inspect it with `{self.read_command}` and retry"
            )
        if state in ("VM stopping", "VM deallocating"):
            self._wait("VM deallocated" if state == "VM deallocating" else "VM stopped")
        self._attach_public_ip()
        if state != "VM starting":
            self._announce("start")
            self._run("start", timeout=600)
        self._wait("VM running")
        return state

    def _announce(self, action):
        announce_designed_wait(
            f"Azure VM {self.instance_id} {action}",
            max_wait_seconds=600,
            cadence=poll_every(5),
            write=self.emit,
        )

    def _wait(self, target):
        self._announce(f"to reach {target}")
        deadline = self.clock() + 600
        while self.clock() < deadline:
            if self._details()["powerState"] == target:
                return
            self.sleeper(5)
        raise AzureAdminError(
            f"Azure VM did not reach {target} within 600s; "
            f"inspect it with `{self.read_command}` and retry"
        )

    def stop(self):
        if self._details()["powerState"] != "VM deallocated":
            # A stopped but allocated VM still bills.
            self._announce("deallocate")
            self._run("deallocate", timeout=600)
            self.emit(f"  deallocated Azure VM {self.instance_id}")
        self._delete_public_ip()

    @property
    def public_ip_id(self):
        group = self.instance_id.split("/providers/", 1)[0]
        name = self.instance_id.rsplit("/", 1)[1]
        return (
            f"{group}/providers/Microsoft.Network/publicIPAddresses/{name}-yoke-power"
        )

    def _network(self, *args):
        return run_checked(
            self.runner.run,
            [*self.command, "network", *args, "--output", "json"],
            self.env,
            action="network " + " ".join(args),
            timeout=120,
        )

    def _ip_config(self):
        details = self._details()
        nics = details.get("networkProfile", {}).get("networkInterfaces", [])
        if len(nics) != 1 or not details.get("location"):
            raise AzureAdminError(
                "Azure power needs one NIC and a location; inspect the VM network profile and retry"
            )
        result = self._network("nic", "show", "--ids", nics[0]["id"])
        try:
            configs = json.loads(result.stdout)["ipConfigurations"]
            (config,) = configs
            config_id = config["id"]
        except (ValueError, KeyError, TypeError):
            raise AzureAdminError(
                "Azure power needs one NIC IP configuration; inspect the NIC and retry"
            ) from None
        attached = (config.get("publicIPAddress") or {}).get("id")
        if attached and attached.lower() != self.public_ip_id.lower():
            raise AzureAdminError(
                f"NIC has unmanaged public IP {attached}; deallocate the VM, detach and delete "
                "the permanent IP through IaC or a recorded operator exception, then retry"
            )
        return config_id, attached, details["location"]

    def _attach_public_ip(self):
        config_id, attached, location = self._ip_config()
        if attached:
            return
        self._network(
            "public-ip",
            "create",
            "--resource-group",
            self.instance_id.split("/resourceGroups/", 1)[1].split("/", 1)[0],
            "--name",
            self.public_ip_id.rsplit("/", 1)[1],
            "--location",
            location,
            "--sku",
            "Standard",
            "--allocation-method",
            "Static",
        )
        self._network(
            "nic",
            "ip-config",
            "update",
            "--ids",
            config_id,
            "--public-ip-address",
            self.public_ip_id,
        )
        self.emit(f"  attached Azure public IP {self.public_ip_id}")

    def _delete_public_ip(self):
        config_id, attached, _ = self._ip_config()
        if attached:
            self._network(
                "nic",
                "ip-config",
                "update",
                "--ids",
                config_id,
                "--remove",
                "publicIPAddress",
            )
        # Listing handles both an absent IP and a create whose attachment failed.
        group = self.instance_id.split("/resourceGroups/", 1)[1].split("/", 1)[0]
        result = self._network("public-ip", "list", "--resource-group", group)
        try:
            ips = json.loads(result.stdout)
            exists = any(ip["id"].lower() == self.public_ip_id.lower() for ip in ips)
        except (ValueError, KeyError, TypeError):
            raise AzureAdminError(
                "Azure public-ip list returned invalid resources; inspect and delete the power IP, then retry"
            ) from None
        if exists:
            self._network("public-ip", "delete", "--ids", self.public_ip_id)
            self.emit(f"  deleted Azure public IP {self.public_ip_id}")
