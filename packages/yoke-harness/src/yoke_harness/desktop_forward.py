"""A bounded desktop route whose SSH listener is held only during its use.

The forward is a plain ``ssh -N -L`` child process owned by this context:
no ControlMaster socket and no ``ssh -f``, so it works with every OpenSSH
client, Windows included. Leaving the context kills the child.
"""

from contextlib import contextmanager
import socket
import subprocess
import time

from yoke_contracts.machine_config.capability_secret_store import machine_capability_secret_path
from yoke_contracts.machine_config.capability_secrets import TEST_MACHINE_CAPABILITY
from yoke_contracts.machine_config.desktop_access import validate_desktop_settings

#: Seconds the forward has to start accepting on its local port.
FORWARD_READY_SECONDS = 20


def _wait_for_listener(process, port, error):
    """Return once 127.0.0.1:port accepts; refuse by name if ssh exits or stalls."""
    deadline = time.monotonic() + FORWARD_READY_SECONDS
    while True:
        if process.poll() is not None:
            raise error(
                "desktop_forward_failed: ssh exited before the forward opened; "
                "check the registered SSH host, key and remote desktop port, then retry"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise error(
                    f"desktop_forward_failed: the SSH forward did not accept on 127.0.0.1:{port} "
                    f"within {FORWARD_READY_SECONDS}s; check the registered SSH host and "
                    "remote desktop port, then retry"
                ) from None
            time.sleep(0.1)


@contextmanager
def _held_forward(project, settings, route, port, error, ssh_args):
    key = machine_capability_secret_path(
        project, TEST_MACHINE_CAPABILITY, "ssh_private_key"
    )
    if not key.is_file():
        raise error(
            "desktop_ssh_key_missing: store test-machine.ssh_private_key on this executing machine"
        )
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        local_port = reservation.getsockname()[1]
    destination = route.get("desktop_host") or "127.0.0.1"
    process = subprocess.Popen(
        [
            *ssh_args(settings, key, "none"),
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-L",
            f"127.0.0.1:{local_port}:[{destination}]:{port}",
            f"{settings['user']}@{settings['host']}",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_listener(process, local_port, error)
        yield local_port
    finally:
        process.kill()
        process.wait()


@contextmanager
def desktop_forward(project, settings):
    from yoke_harness.desktop_access import (
        DesktopAccessError,
        _check_desktop,
        _ssh_args,
    )

    route = validate_desktop_settings(settings)
    if not route:
        raise DesktopAccessError(
            "desktop_route_missing: declare the desktop route with yoke test-machine settings-replace"
        )
    host = route.get("desktop_host") or settings["host"]
    port = int(route["desktop_port"])
    try:
        if route["desktop_route"] == "ssh-forward":
            with _held_forward(
                project, settings, route, port, DesktopAccessError, _ssh_args
            ) as local_port:
                _check_desktop("127.0.0.1", local_port, route["desktop_protocol"])
                yield "127.0.0.1", local_port, route["desktop_user"]
            return
        _check_desktop(host, port, route["desktop_protocol"])
        yield host, port, route["desktop_user"]
    except OSError:
        raise DesktopAccessError(
            "desktop_unreachable: check the declared route and desktop service, then retry"
        ) from None
