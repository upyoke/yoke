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
from yoke_contracts.machine_config.capability_secret_store import (
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
        self._control_path = (None if sys.platform == 'win32' else
                              _control_socket(self._host, self._user, self._key_path))
        facts = self._host_facts()
        self.home = str(facts["home"])
        self.shell = str(facts["shell"])
        self.xdg_bin_home = str(facts.get("xdg_bin_home") or "") or None
        path_env = {"HOME": self.home, "SHELL": self.shell}
        if self.xdg_bin_home:
            path_env["XDG_BIN_HOME"] = self.xdg_bin_home
        self.path_state: PathStateContract = resolve_path_state_contract(target="windows" if self.os == "windows" else "posix", env=path_env)
