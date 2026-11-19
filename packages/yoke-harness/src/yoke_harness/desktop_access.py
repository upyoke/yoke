"""Open a desktop route locally, keeping login credentials off the wire."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import tempfile
from typing import Callable, Mapping

from yoke_contracts.machine_config.capability_secret_store import (
    test_machine_secret_path,
    read_test_machine_secret,
)
from yoke_contracts.owner_private_path import write_owner_private
from yoke_cli.config import machine_config
from yoke_contracts.machine_config.directories import create_private_directory
from yoke_contracts.machine_config.desktop_access import (
    DESKTOP_PASSWORD_KEY,
    validate_desktop_settings,
)
from yoke_harness.test_machine_remote_exec import host_key_options, known_hosts_path


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
        *host_key_options(settings, known_hosts),
        "-S",
        control_path,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
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

    if settings["os"] == "windows":
        # Windows owns its RDP listener and autologon session. Captures use
        # Task Scheduler; a human viewer opens the announced address.
        return {"desktop_session": "native"}, None
    from yoke_harness.linux_desktop_session import ensure_desktop
    from yoke_contracts.windows_wsl_command import (
        windows_wsl_command,
        windows_wsl_input,
    )

    target = f"{settings['user']}@{settings['host']}"

    def run(command, *, input_text=None, timeout=60):
        if settings["os"] == "wsl":
            command, input_text = windows_wsl_input(command, input_text)
            command = windows_wsl_command(command)
        # Without input, ssh must not inherit stdin: it would swallow the Enter
        # that later closes the SSH-forward hold.
        feed = {"input": input_text} if input_text is not None else {"stdin": subprocess.DEVNULL}
        try:
            return subprocess.run(
                [*_ssh_args(settings, key_path, "none"), target, command],
                **feed,
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
    if user.returncode:
        detail = (user.stderr or "SSH command failed").strip()
        if password:
            detail = detail.replace(password, "[REDACTED]")
        raise DesktopAccessError(
            f"desktop_transport_unavailable: {detail}; check the registered SSH/WSL endpoint and retry"
        )
    if user.stdout.strip() != settings["desktop_user"]:
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
                rdp_access=settings["desktop_protocol"] == "rdp",
            )
        )
    except RuntimeError as exc:
        raise DesktopAccessError(str(exc)) from None
    return receipt, run


def _desktop_route(settings):
    route = validate_desktop_settings(settings)
    if not route:
        raise DesktopAccessError(
            "desktop_route_missing: declare the desktop route with yoke test-machine settings-replace"
        )
    return route


def _desktop_password(project, test_machine):
    password = read_test_machine_secret(test_machine, DESKTOP_PASSWORD_KEY)
    if password is None:
        raise DesktopAccessError(
            "desktop_password_missing: import a private password file with "
            f"yoke test-machine secret set --test-machine {test_machine} "
            "--key desktop_password --value-file FILE"
        )
    if "\n" in password or "\r" in password:
        raise DesktopAccessError("desktop_password_invalid: import one password line")
    return password


def _screen_sharing_route(settings, route) -> bool:
    """macOS test machines are viewed in Screen Sharing; Linux and WSL in FreeRDP."""
    if settings.get("os") == "windows":
        raise DesktopAccessError(
            "windows_desktop_view_requires_rdp: run desktop-access without --view and open its announced address in your RDP client"
        )
    if settings.get("os") == "macos" and route["desktop_protocol"] == "vnc":
        return True
    if settings.get("os") in {"linux", "wsl"} and route["desktop_protocol"] == "rdp":
        return False
    raise DesktopAccessError(
        "desktop_view_route_unsupported: --view needs an RDP route on Linux or "
        "Windows WSL, or a VNC route on macOS; run desktop-access without --view"
    )


def _ready_desktop_view(project, test_machine, settings):
    password = _desktop_password(project, test_machine)
    key_path = test_machine_secret_path(
        test_machine, "ssh_private_key"
    )
    if not key_path.is_file():
        raise DesktopAccessError(
            "desktop_ssh_key_missing: import the SSH key with yoke test-machine secret set "
            f"--test-machine {test_machine} --key ssh_private_key --value-file FILE"
        )
    receipt, run = _prepare_desktop(settings, key_path, password)
    return password, receipt, run


def begin_desktop_view(*, project: str, test_machine: str, settings: Mapping[str, str]):
    """Start the desktop-access --view owner and leave it open until close()."""
    if _screen_sharing_route(settings, _desktop_route(settings)):
        from yoke_harness.screen_sharing_view import ScreenSharingView

        password = _desktop_password(project, test_machine)
        return ScreenSharingView.open(project, test_machine, settings, password)
    password, receipt, run = _ready_desktop_view(project, test_machine, settings)
    from yoke_harness.rdp_desktop_client import DesktopView

    return DesktopView.open(project, test_machine, settings, password, receipt, run)


def _hold_forward() -> None:
    """Keep the SSH forward until Enter, Ctrl-C or SIGTERM; without a terminal, until a signal."""
    import signal
    import sys
    import time

    def interrupt(*_):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    print(
        "The SSH forward stays open while this command runs; press Enter or Ctrl-C to close it.",
        file=sys.stderr,
        flush=True,
    )
    try:
        if not sys.stdin.readline():
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)


def open_desktop_access(
    *,
    project: str,
    test_machine: str,
    settings: Mapping[str, str],
    announce: Callable[[dict], None],
    view: bool = False,
) -> None:
    """Announce only the connectable address, desktop user and private file path.

    A direct route announces and returns. The SSH-forward fallback announces,
    then holds its forward until the operator closes it.
    """
    route = _desktop_route(settings)
    if view and _screen_sharing_route(settings, route):
        from yoke_harness.screen_sharing_view import view_screen_sharing

        password = _desktop_password(project, test_machine)
        announce(view_screen_sharing(project, test_machine, settings, password))
        return
    if view:
        password, receipt, run = _ready_desktop_view(project, test_machine, settings)
        from yoke_harness.rdp_desktop_client import view_desktop

        announce(view_desktop(project, test_machine, settings, password, receipt, run))
        return
    password = _desktop_password(project, test_machine)
    session_evidence = {}
    if settings.get("os") in {"linux", "wsl"}:
        key_path = test_machine_secret_path(test_machine, "ssh_private_key")
        if not key_path.is_file():
            raise DesktopAccessError(
                "desktop_ssh_key_missing: import the SSH key with yoke test-machine secret set "
                f"--test-machine {test_machine} --key ssh_private_key --value-file FILE"
            )
        receipt, _ = _prepare_desktop(settings, key_path, password)
        session_evidence = {"desktop_session": receipt["desktop_session"]}
    from yoke_harness.desktop_forward import desktop_forward

    with desktop_forward(project, settings) as (host, port, user):
        if route["desktop_route"] == "direct" and route["desktop_protocol"] == "rdp":
            from yoke_harness.rdp_certificate_pin import pinned_certificate

            session_evidence["certificate_sha256"] = pinned_certificate(
                host, port, DesktopAccessError, yoke_home=machine_config.yoke_home()
            )
        descriptor, name = tempfile.mkstemp(prefix="yoke-desktop-", suffix=".password")
        os.close(descriptor)
        try:
            write_owner_private(Path(name), password + "\n")
        except OSError:
            Path(name).unlink(missing_ok=True)
            raise DesktopAccessError(
                "desktop_password_file_unavailable: repair the workstation temporary "
                "directory permissions and free space, then retry"
            ) from None
        authority = f"[{host}]" if ":" in host else host
        announce(
            {
                "address": f"{route['desktop_protocol']}://{authority}:{port}",
                "route": route["desktop_route"],
                "user": user,
                "password_file": name,
                **session_evidence,
            }
        )
        if route["desktop_route"] == "ssh-forward":
            _hold_forward()
