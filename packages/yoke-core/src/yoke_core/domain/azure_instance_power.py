"""Azure VM power operations; deallocation releases the compute allocation."""

from __future__ import annotations

import ipaddress
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
    executable: str
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
                self.executable,
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

    def address(self):
        address = self._details().get("publicIps")
        if not address:
            return None
        try:
            return str(ipaddress.IPv4Address(address))
        except ipaddress.AddressValueError:
            raise AzureAdminError(
                "Azure VM must expose one public IPv4; repair its public IP and retry"
            ) from None

    def stop(self):
        if self._details()["powerState"] == "VM deallocated":
            return
        # A stopped but allocated VM still bills: deallocate every allocated state.
        self._announce("deallocate")
        self._run("deallocate", timeout=600)
        self.emit(f"  deallocated Azure VM {self.instance_id}")
