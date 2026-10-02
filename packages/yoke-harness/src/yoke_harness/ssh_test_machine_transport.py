"""Shared bounded SSH transport for persistent test machines."""

from __future__ import annotations
from pathlib import Path
import shlex
import subprocess
from typing import Mapping, Sequence
from yoke_cli.config.capability_secrets import (
    machine_capability_secret_path,
    read_machine_capability_secret,
)
from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
    TEST_MACHINE_SECRET_KEYS,
)
from yoke_contracts.machine_qa_execution import HostControlExecutionContract
from yoke_cli.config.path_doctor import PathStateContract, resolve_path_state_contract

SSH_OPTIONS = (
    "StrictHostKeyChecking=accept-new",
    "UserKnownHostsFile=/dev/null",
    "ConnectTimeout=10",
    "BatchMode=yes",
)
SSH_TIMEOUT_DIAGNOSTIC = "host_control subprocess timed out"


class SshTestMachineTransport:
    """SSH execution with OS-specific host facts supplied by each adapter."""

    def __init__(
        self,
        *,
        settings: Mapping[str, str],
        key_path: str | Path,
        secret_values: tuple[str, ...] = (),
    ) -> None:
        self.secret_values = secret_values
        self._key_path = Path(key_path)
        self.os = str(settings["os"])
        self._host = str(settings["host"])
        self._user = str(settings["user"])
        self.golden_baseline_path = (
            str(settings.get("golden_baseline_path") or "") or None
        )
        facts = self._host_facts()
        self.home = str(facts["home"])
        self.shell = str(facts["shell"])
        self.xdg_bin_home = str(facts.get("xdg_bin_home") or "") or None
        path_env = {"HOME": self.home, "SHELL": self.shell}
        if self.xdg_bin_home:
            path_env["XDG_BIN_HOME"] = self.xdg_bin_home
        self.path_state: PathStateContract = resolve_path_state_contract(env=path_env)

    def _ssh_argv(self, command: str) -> list[str]:
        return [
            "ssh",
            "-i",
            str(self._key_path),
            *[part for option in SSH_OPTIONS for part in ("-o", option)],
            f"{self._user}@{self._host}",
            command,
        ]

    def _run(
        self,
        command: str,
        *,
        input_text: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        argv = self._ssh_argv(command)
        try:
            return subprocess.run(
                argv,
                input=input_text,
                encoding="utf-8",
                errors="backslashreplace",
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                argv, returncode=124, stdout="", stderr=SSH_TIMEOUT_DIAGNOSTIC
            )
        except OSError:
            return subprocess.CompletedProcess(
                argv,
                returncode=124,
                stdout="",
                stderr="host_control subprocess unavailable",
            )

    def run_remote_command(
        self,
        command: str,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        """Run one prepared shell command on the host."""
        return self._run(command, timeout=timeout)

    def probe_path(self, surface: str) -> Sequence[str]:
        flag = "-lic" if surface == "login" else "-c"
        probe = "printf '%s' \"$PATH\""
        result = self._run(
            f"{shlex.quote(self.shell)} {flag} {shlex.quote(probe)}",
            timeout=20,
        )
        if result.returncode:
            raise RuntimeError(f"host_control {surface} PATH probe failed")
        return tuple(entry for entry in result.stdout.strip().split(":") if entry)

    @classmethod
    def from_contract(
        cls,
        contract: HostControlExecutionContract,
    ) -> "SshTestMachineTransport":
        """Attach the one registered machine-local credential."""
        secrets: list[str] = []
        secret_paths: dict[str, str] = {}
        missing: list[str] = []
        for key in sorted(TEST_MACHINE_SECRET_KEYS):
            value = read_machine_capability_secret(
                contract.project,
                TEST_MACHINE_CAPABILITY,
                key,
            )
            if value is None:
                missing.append(key)
                continue
            secrets.append(value)
            secret_paths[key] = str(
                machine_capability_secret_path(
                    contract.project,
                    TEST_MACHINE_CAPABILITY,
                    key,
                )
            )
        if missing:
            raise RuntimeError(
                "host_control_credential_missing: "
                + ", ".join(missing)
                + f"; store the key on this executing machine with yoke projects capability secret set --project {contract.project} --cap-type test-machine --key ssh_private_key --value-file KEY_FILE"
            )
        return cls(
            settings=contract.settings,
            key_path=secret_paths["ssh_private_key"],
            secret_values=tuple(secrets),
        )
