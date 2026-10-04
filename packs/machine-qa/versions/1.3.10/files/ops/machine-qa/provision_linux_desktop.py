"""Provision a dedicated Ubuntu test user's XFCE desktop over tunnel-only RDP."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time


DEFAULT_RDP_PORT = 3389
SESSION_CONTENT = "exec startxfce4\n"
TERMINAL_SELECTION = "TerminalEmulator=xfce4-terminal"


class ProvisionFailure(RuntimeError):
    """A named provisioning refusal with an operator recovery."""


def command(
    argv: list[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv, input=input_text, text=True, capture_output=True, timeout=1200
    )
    if result.returncode:
        raise ProvisionFailure(
            f"linux_desktop_command_failed: {argv[0]} exited {result.returncode}; "
            "repair the host dependency or sudo access, then rerun provisioning"
        )
    return result


def desktop_password_input() -> str:
    """Accept only private capability input, never a personal terminal prompt."""
    if sys.stdin.isatty():
        raise ProvisionFailure(
            "desktop_password_input_required: the executing product operation must "
            "feed the capability-owned desktop password on stdin; never type it"
        )
    password = sys.stdin.read(1026).removesuffix("\n")
    if not password or len(password) > 1024 or "\n" in password or "\r" in password:
        raise ProvisionFailure(
            "desktop_password_input_invalid: supply one bounded capability-owned password"
        )
    return password


def set_desktop_password(password: str) -> None:
    """Set only the dedicated fixture login through private product input."""
    import pwd

    user = pwd.getpwuid(os.getuid()).pw_name
    command(["sudo", "-n", "chpasswd"], input_text=f"{user}:{password}\n")


def localhost_config(content: str, port: int = DEFAULT_RDP_PORT) -> str:
    """Change only the listener in Globals, retaining module ports and comments."""
    section = ""
    replaced = 0
    lines = []
    for line in content.splitlines(keepends=True):
        match = re.match(r"\s*\[([^]]+)\]", line)
        if match:
            section = match[1].lower()
        if section == "globals" and re.match(r"\s*port\s*=", line):
            line = f"port=tcp://127.0.0.1:{port}\n"
            replaced += 1
        lines.append(line)
    if replaced != 1:
        raise ProvisionFailure(
            "linux_desktop_listener_config_unavailable: expected one Globals port; "
            "inspect /etc/xrdp/xrdp.ini before rerunning"
        )
    return "".join(lines)


def prove_listener(output: str, port: int = DEFAULT_RDP_PORT) -> None:
    rows = [line.split() for line in output.splitlines() if line.strip()]
    listeners = [row[3] if len(row) >= 5 else "invalid" for row in rows]
    address = f"127.0.0.1:{port}"
    if not listeners or any(value != address for value in listeners):
        raise ProvisionFailure(
            f"linux_desktop_loopback_not_proved: RDP must listen only on {address}; "
            "repair xrdp's Globals port and restart xrdp before connecting"
        )


def terminal_settings(content: str) -> str:
    lines = [
        line
        for line in content.splitlines()
        if not re.match(r"\s*TerminalEmulator\s*=", line)
    ]
    return "\n".join([*lines, TERMINAL_SELECTION]) + "\n"


def prerequisites() -> Path:
    if platform.system() != "Linux" or os.getuid() == 0:
        raise ProvisionFailure(
            "linux_desktop_test_user_required: run as the dedicated non-root Linux "
            "test user with passwordless sudo"
        )
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise ProvisionFailure(
            "linux_desktop_os_unsupported: provision an Ubuntu24.04 test host first"
        )
    command(["sudo", "-n", "true"])
    home = Path.home()
    session = home / ".xsession"
    if session.exists() and session.read_text() != SESSION_CONTENT:
        raise ProvisionFailure(
            "linux_desktop_session_conflict: .xsession already selects another session; "
            "preserve that customization and have the operator select XFCE deliberately"
        )
    return home


def provision(home: Path, port: int = DEFAULT_RDP_PORT) -> None:
    print("linux-desktop: installing XFCE and xrdp", flush=True)
    command(["sudo", "-n", "apt-get", "update"])
    command(
        [
            "sudo",
            "-n",
            "env",
            "DEBIAN_FRONTEND=noninteractive",
            "apt-get",
            "install",
            "-y",
            "--no-install-recommends",
            "xfce4",
            "xfce4-terminal",
            "xrdp",
            "xorgxrdp",
            "dbus-x11",
            "python3-venv",
            "scrot",
            "xdotool",
        ]
    )
    config_path = Path("/etc/xrdp/xrdp.ini")
    original = config_path.read_text()
    configured = localhost_config(original, port)
    if configured != original:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as candidate:
            candidate.write(configured)
            candidate.flush()
            command(
                [
                    "sudo",
                    "-n",
                    "install",
                    "-o",
                    "root",
                    "-g",
                    "root",
                    "-m",
                    "0644",
                    candidate.name,
                    str(config_path),
                ]
            )
    (home / ".xsession").write_text(SESSION_CONTENT)
    (home / ".xsession").chmod(0o600)
    helpers = home / ".config/xfce4/helpers.rc"
    helpers.parent.mkdir(parents=True, exist_ok=True)
    helpers.write_text(
        terminal_settings(helpers.read_text() if helpers.exists() else "")
    )
    command(["sudo", "-n", "usermod", "-aG", "ssl-cert", "xrdp"])
    command(["sudo", "-n", "systemctl", "enable", "--now", "xrdp", "xrdp-sesman"])
    command(["sudo", "-n", "systemctl", "restart", "xrdp"])


def verify(home: Path, port: int = DEFAULT_RDP_PORT) -> dict:
    command(["systemctl", "is-active", "xrdp", "xrdp-sesman"])
    wait_for_listener(port)
    if (home / ".xsession").read_text() != SESSION_CONTENT:
        raise ProvisionFailure(
            "linux_desktop_session_not_proved: rerun provisioning to select XFCE"
        )
    packages = command(
        [
            "dpkg-query",
            "-W",
            "-f=${db:Status-Status}\n",
            "xfce4-session",
            "xfce4-terminal",
            "xorgxrdp",
            "scrot",
            "xdotool",
        ]
    ).stdout.splitlines()
    if packages != ["installed"] * 5:
        raise ProvisionFailure(
            "linux_desktop_packages_not_proved: reinstall XFCE, xfce4-terminal, xorgxrdp, scrot and xdotool"
        )
    helpers = home / ".config/xfce4/helpers.rc"
    if (
        not helpers.is_file()
        or TERMINAL_SELECTION not in helpers.read_text().splitlines()
    ):
        raise ProvisionFailure(
            "linux_desktop_terminal_not_selected: rerun provisioning to select xfce4-terminal"
        )
    status = command(["passwd", "-S"]).stdout.split()
    return {
        "ok": True,
        "desktop": "XFCE",
        "rdp_listener": f"127.0.0.1:{port}",
        "login_password_set": len(status) > 1 and status[1] == "P",
        "operator_next_step": (
            "The product opens the dedicated desktop with its capability-owned secret. "
            "Prove candidate Chromium renders there, then request only personal application sign-in."
        ),
    }


def wait_for_listener(port: int = DEFAULT_RDP_PORT) -> None:
    # systemctl restart returns before xrdp has opened its listening socket.
    deadline = time.monotonic() + 10
    while True:
        output = command(["ss", "-H", "-ltn", f"sport = :{port}"]).stdout
        if output.strip() or time.monotonic() >= deadline:
            prove_listener(output, port)
            return
        time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Readiness check only")
    parser.add_argument("--rdp-port", type=int, default=DEFAULT_RDP_PORT)
    parser.add_argument("--desktop-password-stdin", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.rdp_port <= 65535:
        parser.error("--rdp-port must be between 1 and 65535")
    if args.verify and args.desktop_password_stdin:
        parser.error("--verify does not accept a password or start a desktop")
    if not args.verify and not args.desktop_password_stdin:
        parser.error(
            "provisioning requires --desktop-password-stdin from the capability store"
        )
    try:
        password = desktop_password_input() if args.desktop_password_stdin else None
        home = prerequisites()
        if not args.verify:
            provision(home, args.rdp_port)
        result = verify(home, args.rdp_port)
        if password is not None:
            set_desktop_password(password)
            result["login_password_set"] = True
        result["desktop_session"] = "not_started"
        result["headed_application_proved"] = False
        print(json.dumps(result), flush=True)
        return 0
    except (ProvisionFailure, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"linux_desktop_not_ready: {exc}; inspect the host and rerun", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
