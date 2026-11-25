"""Azure VM power and managed public IP attachment."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.azure_admin import AzureAdminError, run_checked
from yoke_contracts.machine_fixture_verify import MachineFixtureFailed, verify_records
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
    def stop_command(self) -> str:
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

    def run_script(self, script: str, timeout: int) -> list[dict[str, Any]]:
        """Run one PowerShell script as SYSTEM on the VM through run-command.

        Run-command reports no script exit code, so the script's verify
        records are the proof: a non-zero CLI exit, a missing record or a
        failed record refuses with the script's stderr.
        """
        with tempfile.TemporaryDirectory(prefix="yoke-run-command-") as directory:
            path = Path(directory) / "script.ps1"
            path.write_text(script, encoding="utf-8")
            argv = [
                *self.command, "vm", "run-command", "invoke", "--ids", self.instance_id,
                "--command-id", "RunPowerShellScript", "--scripts", "@" + str(path),
                "--output", "json",
            ]
            try:
                result = self.runner.run(argv, env=self.env, timeout=timeout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise self._script_failed([], f"Azure run-command did not finish ({type(exc).__name__})") from None
        stdout = stderr = ""
        try:
            for status in json.loads(result.stdout or "{}").get("value", []):
                if "/StdOut/" in str(status.get("code")):
                    stdout += str(status.get("message") or "")
                elif "/StdErr/" in str(status.get("code")):
                    stderr += str(status.get("message") or "")
        except (ValueError, AttributeError):
            stderr = result.stdout
        records = verify_records(stdout)
        if result.returncode:
            raise self._script_failed(records, (result.stderr or stderr).strip()[-2000:])
        if not records or any(record.get("ok") is not True for record in records):
            raise self._script_failed(records, stderr.strip()[-2000:] or "the script printed no verify record")
        return records

    def _script_failed(self, records, stderr):
        return MachineFixtureFailed(
            records=records,
            detail=f"SYSTEM script on Azure VM {self.instance_id} failed",
            stderr=stderr,
            recovery_hint=(
                "Read the verify records and stderr, repair the named state, then retry; "
                "if Azure reports a run-command already in progress, wait for it and retry"
            ),
        )

    def stop(self):
        if self._details()["powerState"] != "VM deallocated":
            # A stopped but allocated VM still bills.
            self._announce("deallocate")
            self._run("deallocate", timeout=600)
            self._wait("VM deallocated")
            self.emit(f"  deallocated Azure VM {self.instance_id}")
        self._delete_public_ip()

    @property
    def public_ip_id(self):
        group = "/".join(self.instance_id.split("/")[:5])
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

    @staticmethod
    def _ip_config_selectors(config_id: str) -> tuple[str, str, str]:
        selectors = re.fullmatch(
            r"/subscriptions/[^/]+/resourceGroups/([^/]+)/providers/"
            r"Microsoft\.Network/networkInterfaces/([^/]+)/ipConfigurations/([^/]+)",
            config_id,
            flags=re.IGNORECASE,
        )
        if selectors is None:
            raise AzureAdminError(
                "Azure NIC IP configuration id is invalid; inspect the NIC and retry"
            )
        return selectors.groups()

    def _update_public_ip(self, selectors: tuple[str, str, str], address: str):
        resource_group, nic_name, config_name = selectors
        self._network(
            "nic",
            "ip-config",
            "update",
            "--resource-group",
            resource_group,
            "--nic-name",
            nic_name,
            "--name",
            config_name,
            "--public-ip-address",
            address,
        )

    def _attach_public_ip(self):
        config_id, attached, location = self._ip_config()
        if attached:
            return
        selectors = self._ip_config_selectors(config_id)
        self._network(
            "public-ip",
            "create",
            "--resource-group",
            self.instance_id.split("/")[4],
            "--name",
            self.public_ip_id.rsplit("/", 1)[1],
            "--location",
            location,
            "--sku",
            "Standard",
            "--allocation-method",
            "Static",
        )
        self._update_public_ip(selectors, self.public_ip_id)
        self.emit(f"  attached Azure public IP {self.public_ip_id}")

    def _delete_public_ip(self):
        config_id, attached, _ = self._ip_config()
        if attached:
            self._update_public_ip(self._ip_config_selectors(config_id), "null")

        # Also find a managed IP left behind by an unsuccessful attachment.
        group = self.instance_id.split("/")[4]
        result = self._network("public-ip", "list", "--resource-group", group)
        try:
            resources = json.loads(result.stdout)
            if not isinstance(resources, list):
                raise ValueError("expected a list of public IP resources")
            resource_ids = {ip["id"].lower() for ip in resources}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise AzureAdminError(
                "Azure public-ip list returned invalid resources; inspect and delete the power IP, then retry"
            ) from None
        if self.public_ip_id.lower() in resource_ids:
            self._network("public-ip", "delete", "--ids", self.public_ip_id)
            self.emit(f"  deleted Azure public IP {self.public_ip_id}")
