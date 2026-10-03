"""A bounded desktop route whose SSH listener is held only during its use."""

from contextlib import contextmanager
from pathlib import Path
import socket
import shutil
import subprocess
import tempfile

from yoke_cli.config.capability_secrets import machine_capability_secret_path
from yoke_contracts.machine_config.capability_secrets import TEST_MACHINE_CAPABILITY
from yoke_contracts.machine_config.desktop_access import validate_desktop_settings


@contextmanager
def desktop_forward(project, settings):
    from yoke_harness.desktop_access import (
        DesktopAccessError,
        _check_desktop,
        _ssh_args,
    )

    route = validate_desktop_settings(settings)
    if not route or route["desktop_protocol"] != "rdp":
        raise DesktopAccessError(
            "desktop_rdp_route_required: register the RDP desktop route with yoke test-machine settings-replace"
        )
    host = route.get("desktop_host") or settings["host"]
    port = int(route["desktop_port"])
    directory = tempfile.mkdtemp(prefix="yoke-rdp-", dir="/tmp")
    preserve_socket = False
    try:
        control_path = str(Path(directory) / "ssh")
        args = []
        target = f"{settings['user']}@{settings['host']}"
        attempted = False
        try:
            if route["desktop_route"] == "ssh-forward":
                key = machine_capability_secret_path(
                    project, TEST_MACHINE_CAPABILITY, "ssh_private_key"
                )
                if not key.is_file():
                    raise DesktopAccessError(
                        "desktop_ssh_key_missing: store test-machine.ssh_private_key on this executing machine"
                    )
                args = _ssh_args(settings, key, control_path)
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    local_port = reservation.getsockname()[1]
                destination = route.get("desktop_host") or "127.0.0.1"
                attempted = True
                result = subprocess.run(
                    [
                        *args,
                        "-M",
                        "-f",
                        "-N",
                        "-o",
                        "ExitOnForwardFailure=yes",
                        "-L",
                        f"127.0.0.1:{local_port}:[{destination}]:{port}",
                        target,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=20,
                    check=False,
                )
                if result.returncode:
                    raise DesktopAccessError(
                        "desktop_forward_failed: check the registered SSH host, key and remote desktop port, then retry"
                    )
                host, port = "127.0.0.1", local_port
            _check_desktop(host, port, "rdp")
            yield host, port, route["desktop_user"]
        except (OSError, subprocess.TimeoutExpired):
            raise DesktopAccessError(
                "desktop_unreachable: check the declared route and desktop service, then retry"
            ) from None
        finally:
            if attempted:
                try:
                    result = subprocess.run(
                        [*args, "-O", "exit", target],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                        check=False,
                    )
                    if result.returncode and Path(control_path).exists():
                        raise OSError("forward still present")
                except (OSError, subprocess.TimeoutExpired):
                    preserve_socket = True
                    raise DesktopAccessError(
                        f"desktop_forward_cleanup_failed: close the forward with ssh -F /dev/null -S {control_path} -O exit {target}"
                    ) from None
    finally:
        if not preserve_socket:
            shutil.rmtree(directory)
