"""Shared bounded SSH transport for persistent test machines."""

from __future__ import annotations
from pathlib import Path
import hashlib
import os
import stat
import sys
import time
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
from yoke_harness.test_machine_remote_exec import host_key_options
from yoke_contracts.machine_config.scratch_roots import scratch_root_candidates
from yoke_cli.config.path_doctor import PathStateContract, resolve_path_state_contract
from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic

# Keep SSH connection diagnostics focused on failures.
SSH_OPTIONS = (
    "StrictHostKeyChecking=accept-new",
    "LogLevel=ERROR",
    "ConnectTimeout=10",
    "BatchMode=yes",
    "ControlMaster=auto",
    "ControlPersist=30",
)
# The runner reports its own failures to start or finish ssh as this exit
# code, so callers can tell a runner-side stop from a remote command's exit.
TRANSPORT_FAILURE_EXIT = 124
SSH_TIMEOUT_DIAGNOSTIC = "host_control subprocess timed out"
SSH_UNAVAILABLE_DIAGNOSTIC = "host_control subprocess unavailable"
SSH_REUSE_WARNING = (
    "host_control_ssh_stale_socket: SSH master unavailable; "
    "OpenSSH will open a fresh connection before executing the command. "
    "If repeated, wait 30 seconds for "
    "the master to expire and retry the host command."
)
# OpenSSH already falls back on these pre-execution errors. Never replay the
# command: a later exit 255 may belong to a command that actually ran.
_STALE_SOCKET_ERRORS = (
    "mux_client_hello_exchange:",
    "mux_client_request_session: session request failed:",
    "Control socket connect(",
)


def _control_socket(host: str, user: str, key_path: Path) -> Path:
    identity = "\0".join((host, user, str(key_path.resolve())))
    name = hashlib.sha256(identity.encode()).hexdigest()[:24]
    try:
        # Reuse Yoke's scratch resolution, choosing a root that can hold a
        # Unix socket plus OpenSSH's temporary suffix on macOS and Linux.
        socket = next(
            (
                root / f"ssh-{os.getuid()}" / name
                for root in scratch_root_candidates()
                if len(os.fsencode(root / f"ssh-{os.getuid()}" / name)) <= 85
            ),
            None,
        )
        if socket is None:
            raise OSError("scratch paths are too long for an SSH control socket")
        directory = socket.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("socket directory must be owned by the executing user")
        directory.chmod(0o700)
        return socket
    except OSError as exc:
        raise RuntimeError(
            "host_control_ssh_socket_unavailable: "
            + str(exc)
            + "; configure a short writable Yoke temp_root and retry the host command"
        ) from exc


def _partial_output(value, secrets):
    # TimeoutExpired carries bytes even when run() requested text output.
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="backslashreplace")
    return bounded_machine_qa_diagnostic(value, secrets)


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
        self._host_key_options = host_key_options(settings)
        self._user = str(settings["user"])
        self.golden_baseline_path = (
            str(settings.get("golden_baseline_path") or "") or None
        )
        self._control_path = _control_socket(self._host, self._user, self._key_path)
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
            *getattr(self, "_host_key_options", []),
            "-o",
            f"ControlPath={self._control_path}",
            f"{self._user}@{self._host}",
            command,
        ]

    def _run(
        self,
        command: str,
        *,
        input_text: str | None = None,
        timeout: int = 60,
        debug_log: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv = self._ssh_argv(command)
        if debug_log is not None:
            argv[1:1] = ["-vvv", "-E", str(debug_log)]
        started = time.monotonic()
        try:
            control_path = getattr(self, "_control_path", None)
            warned = False
            if control_path is not None and control_path.exists():
                # A control request never executes a remote command. It also
                # exposes ECONNREFUSED, which auto mode logs only at DEBUG.
                try:
                    probe = subprocess.run(
                        argv[:1] + ["-O", "check"] + argv[1:-1],
                        capture_output=True,
                        encoding="utf-8",
                        errors="backslashreplace",
                        timeout=min(5, timeout / 2),
                        check=False,
                    )
                    warned = probe.returncode != 0
                except subprocess.TimeoutExpired:
                    warned = True
                if warned:
                    print(SSH_REUSE_WARNING, file=sys.stderr)
            result = subprocess.run(
                argv,
                input=input_text,
                encoding="utf-8",
                errors="backslashreplace",
                capture_output=True,
                timeout=max(0.001, timeout - (time.monotonic() - started)),
                check=False,
            )
            if not warned and any(
                marker in result.stderr for marker in _STALE_SOCKET_ERRORS
            ):
                print(SSH_REUSE_WARNING, file=sys.stderr)
            return result
        except subprocess.TimeoutExpired as exc:
            stderr = _partial_output(exc.stderr, self.secret_values)
            return subprocess.CompletedProcess(
                argv,
                returncode=TRANSPORT_FAILURE_EXIT,
                stdout=_partial_output(exc.stdout, self.secret_values),
                stderr=SSH_TIMEOUT_DIAGNOSTIC + (f": {stderr}" if stderr else ""),
            )
        except OSError as exc:
            return subprocess.CompletedProcess(
                argv,
                returncode=TRANSPORT_FAILURE_EXIT,
                stdout="",
                stderr=f"{SSH_UNAVAILABLE_DIAGNOSTIC}: {type(exc).__name__}: "
                + _partial_output(str(exc), self.secret_values),
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
