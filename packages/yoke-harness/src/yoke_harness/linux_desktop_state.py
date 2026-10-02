"""Remote Linux desktop discovery and ownership; uses only host stdlib."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time

RECOVERY = "Log in over RDP as the registered desktop user and leave one XFCE session unlocked."
RDP_PORT = 3389
DESKTOP_READY_TIMEOUT_SECONDS = 15
DESKTOP_POLL_INTERVAL_SECONDS = 0.2


def desktop_sessions():
    sessions = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / "comm").read_text().strip() != "xfce4-session":
                continue
            if process.stat().st_uid != os.getuid():
                raise RuntimeError("linux_desktop_other_user: " + RECOVERY)
            environment = dict(
                field.split("=", 1)
                for field in (process / "environ").read_bytes().decode().split("\0")
                if "=" in field
            )
            if environment.get("DISPLAY"):
                sessions.append(
                    {
                        "pid": int(process.name),
                        "start": (process / "stat")
                        .read_text()
                        .rsplit(")", 1)[1]
                        .split()[19],
                        "session_id": environment.get("XDG_SESSION_ID", ""),
                        "environment": {
                            "DISPLAY": environment["DISPLAY"],
                            "XAUTHORITY": environment.get(
                                "XAUTHORITY", str(Path.home() / ".Xauthority")
                            ),
                            "DBUS_SESSION_BUS_ADDRESS": environment.get(
                                "DBUS_SESSION_BUS_ADDRESS", ""
                            ),
                        },
                    }
                )
        except (FileNotFoundError, ProcessLookupError):
            continue
    return sessions


def graphical_sessions():
    if not Path("/run/systemd/system").is_dir():
        return []
    listed = subprocess.run(
        ["loginctl", "list-sessions", "--no-legend", "--no-pager"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if listed.returncode:
        raise RuntimeError("linux_desktop_state_unknown: " + listed.stderr + RECOVERY)
    sessions = []
    for line in listed.stdout.splitlines():
        fields = line.split()
        if not fields:
            continue
        result = subprocess.run(
            [
                "loginctl",
                "show-session",
                fields[0],
                "--no-pager",
                "-p",
                "Type",
                "-p",
                "User",
                "-p",
                "State",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode:
            raise RuntimeError(
                "linux_desktop_state_unknown: " + result.stderr + RECOVERY
            )
        properties = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        if properties.get("Type") in {"x11", "wayland"}:
            sessions.append({"id": fields[0], **properties})
    return sessions


def rdp_connected(port=RDP_PORT):
    # A connected RDP client can adopt a session Yoke originally started.
    for name in ("tcp", "tcp6"):
        for line in (Path("/proc/net") / name).read_text().splitlines()[1:]:
            fields = line.split()
            if int(fields[1].rsplit(":", 1)[1], 16) == port and fields[3] == "01":
                return True
    return False


def ownership_file(*, create=True):
    import fcntl

    path = Path(f"/tmp/yoke-desktop-{os.getuid()}.json")
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0), 0o600)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        os.close(fd)
        raise RuntimeError(
            "linux_desktop_ownership_unsafe: repair the owner-only desktop ownership file; "
            + RECOVERY
        )
    stream = os.fdopen(fd, "r+")
    fcntl.flock(stream, fcntl.LOCK_EX)
    return stream


def owned_desktop():
    if (
        not Path("/proc").exists()
        or not Path(f"/tmp/yoke-desktop-{os.getuid()}.json").exists()
    ):
        return None
    with ownership_file(create=False) as stream:
        try:
            saved = json.load(stream)
        except ValueError:
            return None
    if not isinstance(saved, dict):
        raise RuntimeError(
            "linux_desktop_ownership_invalid: repair the desktop ownership file; "
            + RECOVERY
        )
    for session in desktop_sessions():
        if session == saved.get("session"):
            return {**session, "rdp_port": saved["rdp_port"]}
    return None


def human_desktop_exists(home, owned=None):
    """Shared startup/reset admission, including a human adopting our desktop."""
    redirected = str(Path(home) / "thinclient_drives")
    if os.path.ismount(redirected):
        return True
    proc = Path("/proc")
    if proc.exists():
        for line in (proc / "self/mountinfo").read_text().splitlines():
            target = line.split()[4].replace("\\040", " ").replace("\\134", "\\")
            if target == redirected or target.startswith(redirected + "/"):
                return True
        for directory in proc.iterdir():
            if not directory.name.isdigit():
                continue
            try:
                if (directory / "comm").read_text().strip() == "xfce4-session":
                    if owned is None or int(directory.name) != owned["pid"]:
                        return True
            except (FileNotFoundError, ProcessLookupError):
                pass
    for session in graphical_sessions():
        if owned is None or session["id"] != owned["session_id"]:
            return True
    return owned is not None and rdp_connected(owned["rdp_port"])


def ensure_desktop(password, port=RDP_PORT):
    import pwd

    with ownership_file() as stream:
        sessions = desktop_sessions()
        if len(sessions) == 1:
            return {
                "environment": sessions[0]["environment"],
                "desktop_session": "reused",
            }
        if sessions or human_desktop_exists(Path.home()) or rdp_connected(port):
            raise RuntimeError(
                "linux_desktop_session_ambiguous: a desktop session or RDP client already exists; "
                + RECOVERY
            )
        if not password:
            raise RuntimeError(
                "desktop_password_missing: store desktop_password in the registered test-machine capability secret store; "
                + RECOVERY
            )
        try:
            result = subprocess.run(
                [
                    "xrdp-sesrun",
                    "-s",
                    "::1",
                    "-t",
                    "Xorg",
                    "-F",
                    "0",
                    pwd.getpwuid(os.getuid()).pw_name,
                ],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                "linux_desktop_start_failed: "
                + str(exc).replace(password, "[REDACTED]")
                + "; "
                + RECOVERY
            ) from None
        diagnostic = (result.stdout + result.stderr).replace(password, "[REDACTED]")
        display = re.search(r"\bok data=1 display=(:\d+)\b", result.stdout)
        if result.returncode or not display:
            raise RuntimeError(
                "linux_desktop_start_failed: " + diagnostic + "; " + RECOVERY
            )
        deadline = time.monotonic() + DESKTOP_READY_TIMEOUT_SECONDS
        while True:
            sessions = desktop_sessions()
            if (
                len(sessions) == 1
                and sessions[0]["environment"]["DISPLAY"].split(".", 1)[0] == display[1]
            ):
                stream.seek(0)
                json.dump({"session": sessions[0], "rdp_port": port}, stream)
                stream.truncate()
                stream.flush()
                return {
                    "environment": sessions[0]["environment"],
                    "desktop_session": "started",
                }
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "linux_desktop_start_not_ready: " + diagnostic + "; " + RECOVERY
                )
            time.sleep(DESKTOP_POLL_INTERVAL_SECONDS)


def stop_owned_desktop():
    session = owned_desktop()
    if session is None:
        return
    if human_desktop_exists(Path.home(), session):
        raise RuntimeError(
            "linux_reset_desktop_logged_in: disconnect the human RDP client before resetting"
        )
    if not any(
        row["pid"] == session["pid"] and row["start"] == session["start"]
        for row in desktop_sessions()
    ):
        return
    os.kill(session["pid"], signal.SIGTERM)
    deadline = time.monotonic() + DESKTOP_READY_TIMEOUT_SECONDS
    while any(
        row["pid"] == session["pid"] and row["start"] == session["start"]
        for row in desktop_sessions()
    ) or any(row["id"] == session["session_id"] for row in graphical_sessions()):
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "linux_desktop_stop_not_proved: log out the Yoke-started desktop, then retry reset"
            )
        time.sleep(DESKTOP_POLL_INTERVAL_SECONDS)
    with ownership_file() as stream:
        stream.seek(0)
        stream.truncate()
