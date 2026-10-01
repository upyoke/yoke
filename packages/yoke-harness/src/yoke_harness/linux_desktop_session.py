"""Find the leased Linux user's actual XFCE display instead of assuming :0."""

from __future__ import annotations

import json
import shlex
from pathlib import Path


def desktop_environment() -> dict[str, str]:
    """Read only this user's desktop session environment from procfs."""
    import os

    sessions = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            if (process / "comm").read_text().strip() != "xfce4-session":
                continue
            environment = dict(
                field.split("=", 1)
                for field in (process / "environ").read_bytes().decode().split("\0")
                if "=" in field
            )
            display = environment.get("DISPLAY", "")
            if display:
                sessions.append(
                    {
                        "DISPLAY": display,
                        "XAUTHORITY": environment.get(
                            "XAUTHORITY", str(Path.home() / ".Xauthority")
                        ),
                        "DBUS_SESSION_BUS_ADDRESS": environment.get(
                            "DBUS_SESSION_BUS_ADDRESS", ""
                        ),
                    }
                )
        except (OSError, UnicodeError, ValueError):
            continue
    distinct = {json.dumps(value, sort_keys=True) for value in sessions}
    if len(distinct) != 1:
        raise RuntimeError(
            "linux_desktop_session_required: provision the dedicated test user's "
            "XFCE desktop with ops/machine-qa/provision_linux_desktop.py, open its "
            "tunnel-only RDP session, and leave exactly one session unlocked"
        )
    return json.loads(distinct.pop())


def desktop_command(control, argv: list[str], *, timeout: int = 60):
    """Run a command on the same display desktop screenshots capture."""
    source = Path(__file__).read_text()
    probe = control._run(
        shlex.join(
            [
                "/usr/bin/python3",
                "-c",
                source + "\nprint(json.dumps(desktop_environment()))",
            ]
        ),
        timeout=20,
    )
    if probe.returncode:
        raise RuntimeError("linux_desktop_session_required: " + probe.stderr[-1000:])
    environment = json.loads(probe.stdout)
    return control._run(
        shlex.join(
            [
                "env",
                *[f"{key}={value}" for key, value in environment.items()],
                *argv,
            ]
        ),
        timeout=timeout,
    )
