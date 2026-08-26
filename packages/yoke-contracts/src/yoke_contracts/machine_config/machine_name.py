"""The name this machine's operator gave it, for surfaces people read."""

from __future__ import annotations

import socket
import subprocess
import sys


PROBE_TIMEOUT_SECONDS = 2


def _probe(command: tuple[str, ...]) -> str:
    """Return a command's trimmed stdout, or ``""`` when it cannot answer."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def machine_display_name() -> str:
    """Return the operator-set machine name, falling back to the host name.

    ``socket.gethostname()`` answers with whatever the network handed the
    host, which on macOS is a truncated DHCP-assigned label — a machine whose
    owner named it ``beebauman-macbook-pro-16`` answers ``Mac``. Two people on
    default-named laptops then become indistinguishable on any roster that
    shows the result. Ask the platform for the name its operator chose first,
    and keep the network name as the fallback that always answers.
    """
    if sys.platform == "darwin":
        chosen = _probe(("scutil", "--get", "ComputerName"))
    elif sys.platform.startswith("linux"):
        # systemd's "pretty" hostname is the operator-set one. It is
        # routinely unset, and an unset value reports as empty output.
        chosen = _probe(("hostnamectl", "--pretty"))
    else:
        # Windows already resolves the operator-set name through the host
        # name, so the fallback is the answer rather than a degraded one.
        chosen = ""
    return chosen or socket.gethostname()


__all__ = ["PROBE_TIMEOUT_SECONDS", "machine_display_name"]
