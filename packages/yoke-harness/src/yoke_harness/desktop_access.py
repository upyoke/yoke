"""Open a desktop route locally, keeping login credentials off the wire."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import tempfile
from typing import Mapping

from yoke_cli.config.capability_secrets import (
    machine_capability_secret_path,
    read_machine_capability_secret,
)
from yoke_cli.config import machine_config
from yoke_contracts.machine_config.directories import create_private_directory
from yoke_contracts.machine_config.capability_secrets import TEST_MACHINE_CAPABILITY
from yoke_contracts.machine_config.desktop_access import (
    DESKTOP_PASSWORD_KEY,
    validate_desktop_settings,
)
from yoke_contracts.machine_config.test_machine import test_machine_capability_type
from yoke_harness.test_machine_remote_exec import known_hosts_path


class DesktopAccessError(RuntimeError):
    """A named failure with recovery safe to print without credential values."""


def _ssh_args(
    settings: Mapping[str, str], key_path: Path, control_path: str
) -> list[str]:
    known_hosts = known_hosts_path(machine_config.yoke_home())
    create_private_directory(known_hosts.parent)
    return [
        "ssh",
        "-F",
        "/dev/null",
        "-i",
        str(key_path),
        "-S",
        control_path,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
    ]


def _check_desktop(host: str, port: int, protocol: str) -> None:
    """A tunnel listener alone does not prove its remote desktop is reachable."""
    with socket.create_connection((host, port), timeout=10) as connection:
        if protocol == "rdp":
            connection.sendall(bytes.fromhex("030000130ee000000000000100080003000000"))
            prefix = _read_prefix(connection)
            if prefix[:2] != b"\x03\x00" or int.from_bytes(prefix[2:], "big") < 11:
                raise OSError("RDP handshake unavailable")
        elif _read_prefix(connection) != b"RFB ":
            raise OSError("VNC handshake unavailable")


def _read_prefix(connection: socket.socket) -> bytes:
    prefix = b""
    while len(prefix) < 4:
        chunk = connection.recv(4 - len(prefix))
        if not chunk:
            raise OSError("Desktop handshake closed")
        prefix += chunk
    return prefix


def _prepare_desktop(settings, key_path, password):
    """Use the same framed WSL transport and XFCE helper as GUI operations."""
    from types import SimpleNamespace
    from yoke_harness.linux_desktop_session import ensure_desktop
    from yoke_harness.windows_wsl_command import windows_wsl_command, windows_wsl_input

    target = f"{settings['user']}@{settings['host']}"

    def run(command, *, input_text=None, timeout=60):
        if settings["os"] == "windows":
            command, input_text = windows_wsl_input(command, input_text)
            command = windows_wsl_command(command)
        try:
            return subprocess.run(
                [*_ssh_args(settings, key_path, "none"), target, command],
                input=input_text,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise DesktopAccessError(
                "desktop_transport_unavailable: check the registered SSH/WSL endpoint and retry"
            ) from None

    user = run("id -un", timeout=20)
    if user.returncode or user.stdout.strip() != settings["desktop_user"]:
        raise DesktopAccessError(
            "desktop_user_mismatch: register the dedicated Linux/WSL user's desktop_user and xrdp port; rerun desktop-access"
        )
    try:
        receipt = ensure_desktop(
            SimpleNamespace(
                _run=run,
                desktop_password=password,
                secret_values=(password,),
                desktop_port=int(settings["desktop_port"]),
            )
        )
    except RuntimeError as exc:
        raise DesktopAccessError(str(exc)) from None
    return receipt, run


def open_desktop_access(
    *, project: str, machine: str, settings: Mapping[str, str], view: bool = False
) -> dict[str, str]:
    """Return only the connectable address, desktop user and private file path."""
    route = validate_desktop_settings(settings)
    if not route:
        raise DesktopAccessError(
            "desktop_route_missing: declare the desktop route with yoke test-machine settings-replace"
        )
    if view and (
        settings.get("os") not in {"linux", "windows"}
        or route["desktop_protocol"] != "rdp"
    ):
        raise DesktopAccessError(
            "desktop_view_requires_xfce_rdp: use the declared RDP route on Linux or Windows WSL"
        )
    cap_type = test_machine_capability_type(machine)
    password = read_machine_capability_secret(project, cap_type, DESKTOP_PASSWORD_KEY)
    if password is None:
        raise DesktopAccessError(
            "desktop_password_missing: import a private password file with "
            f"yoke projects capability secret set --project {project} --cap-type {cap_type} "
            "--key desktop_password --value-file FILE"
        )
    if "\n" in password or "\r" in password:
        raise DesktopAccessError("desktop_password_invalid: import one password line")
    key_path = machine_capability_secret_path(
        project, TEST_MACHINE_CAPABILITY, "ssh_private_key"
    )
    if route["desktop_route"] == "ssh-forward" and not key_path.is_file():
        raise DesktopAccessError(
            "desktop_ssh_key_missing: store test-machine.ssh_private_key on this executing machine"
        )
    session_evidence = {}
    if settings.get("os") in {"linux", "windows"}:
        if not key_path.is_file():
            raise DesktopAccessError(
                "desktop_ssh_key_missing: store test-machine.ssh_private_key on this executing machine"
            )
        receipt, run = _prepare_desktop(settings, key_path, password)
        session_evidence = {"desktop_session": receipt["desktop_session"]}
    if view:
        from yoke_harness.rdp_desktop_client import view_desktop

        return view_desktop(project, machine, settings, password, receipt, run)
    descriptor, name = tempfile.mkstemp(
        prefix="yoke-desktop-", suffix=".password", dir="/tmp"
    )
    password_path = Path(name)
    control_path = name + ".ssh"
    ssh_args: list[str] = []
    target = f"{settings['user']}@{settings['host']}"
    tunnel = False
    opened = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(password + "\n")
        host = route.get("desktop_host") or settings["host"]
        port = int(route["desktop_port"])
        if route["desktop_route"] == "ssh-forward":
            ssh_args = _ssh_args(settings, key_path, control_path)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                local_port = reservation.getsockname()[1]
            destination = route.get("desktop_host") or "127.0.0.1"
            forward = f"127.0.0.1:{local_port}:[{destination}]:{port}"
            result = subprocess.run(
                [
                    *ssh_args,
                    "-M",
                    "-f",
                    "-N",
                    "-o",
                    "ExitOnForwardFailure=yes",
                    "-L",
                    forward,
                    target,
                ],
                capture_output=True,
                timeout=20,
                check=False,
            )
            if result.returncode:
                raise DesktopAccessError(
                    "desktop_forward_failed: check the registered SSH host, key and remote desktop port, then retry"
                )
            tunnel = True
            host, port = "127.0.0.1", local_port
        _check_desktop(host, port, route["desktop_protocol"])
        authority = f"[{host}]" if ":" in host else host
        opened = True
        return {
            "address": f"{route['desktop_protocol']}://{authority}:{port}",
            "user": route["desktop_user"],
            "password_file": name,
            **session_evidence,
        }
    except (OSError, subprocess.TimeoutExpired):
        raise DesktopAccessError(
            "desktop_unreachable: check the declared route and desktop service, then retry"
        ) from None
    finally:
        # A failed open must not leave either a password copy or an SSH listener.
        if not opened:
            password_path.unlink(missing_ok=True)
            if tunnel or Path(control_path).exists():
                try:
                    closed = subprocess.run(
                        [*ssh_args, "-O", "exit", target],
                        capture_output=True,
                        timeout=10,
                        check=False,
                    )
                    if closed.returncode:
                        raise DesktopAccessError(
                            "desktop_forward_cleanup_failed: close the forward with "
                            f"ssh -F /dev/null -S {control_path} -O exit {target}"
                        )
                except (OSError, subprocess.TimeoutExpired):
                    raise DesktopAccessError(
                        "desktop_forward_cleanup_failed: close the forward with "
                        f"ssh -F /dev/null -S {control_path} -O exit {target}"
                    ) from None
