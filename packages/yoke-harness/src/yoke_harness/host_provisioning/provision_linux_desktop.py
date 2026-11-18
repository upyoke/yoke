"""Provision a dedicated Ubuntu test user's XFCE desktop over tailnet or SSH-forward RDP."""

from __future__ import annotations

from yoke_contracts.owner_private_path import posix_uid

import argparse
import json
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import tempfile
import time

from linux_desktop_listener import (
    ANY_ADDRESS,
    ProvisionFailure,
    install_firewall,
    listener_config,
    prove_firewall,
    prove_listener,
)

DEFAULT_RDP_PORT = 3389
SESSION_CONTENT = "exec startxfce4\n"
TERMINAL_SELECTION = "TerminalEmulator=xfce4-terminal"
BROWSER_SELECTION = "WebBrowser=yoke-identity-browser"
HELPER_PACKAGES = ("xfce4-helpers", "xdg-utils", "libgtk-3-bin")
# Web links open in the operator identity's signed-in browser through `yoke
# browser open`, the test machine's only login store. The entry is in the home
# golden, so resets keep it; a clean baseline without Yoke has no launcher yet.
LAUNCHER_DESKTOP_ENTRY = "yoke-identity-browser.desktop"
BROWSER_HELPER_PATH = Path(".local/share/xfce4/helpers") / LAUNCHER_DESKTOP_ENTRY
BROWSER_HELPER = (
    "[Desktop Entry]\nType=X-XFCE-Helper\nName=Yoke identity browser\n"
    "X-XFCE-Category=WebBrowser\n"
    f"X-XFCE-Commands=gtk-launch -- {LAUNCHER_DESKTOP_ENTRY} about:blank;\n"
    f'X-XFCE-CommandsWithParameter=gtk-launch -- {LAUNCHER_DESKTOP_ENTRY} "%s";\n'
)
DEFAULTS_SECTION = "[Default Applications]"
BROWSER_TYPES = ("x-scheme-handler/http", "x-scheme-handler/https", "text/html")


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

    user = pwd.getpwuid(posix_uid()).pw_name
    command(["sudo", "-n", "chpasswd"], input_text=f"{user}:{password}\n")


def helper_settings(content: str) -> str:
    lines = [
        line
        for line in content.splitlines()
        if not re.match(r"\s*(TerminalEmulator|WebBrowser)\s*=", line)
    ]
    return "\n".join([*lines, TERMINAL_SELECTION, BROWSER_SELECTION]) + "\n"


def launcher_entry(project: str, identity: str) -> str:
    """The desktop entry routing web links to the identity launcher."""
    opener = "exec yoke browser open --project %s --identity %s \"$0\"" % (
        shlex.quote(project),
        shlex.quote(identity),
    )
    return (
        "[Desktop Entry]\nType=Application\nName=Yoke identity browser\n"
        "Exec=bash -lc " + shlex.quote(opener) + " %u\nNoDisplay=true\n"
        "MimeType=x-scheme-handler/http;x-scheme-handler/https;text/html;\n"
    )


def browser_defaults(content: str) -> str:
    """Select the launcher for web links without erasing other defaults."""
    selections = [f"{kind}={LAUNCHER_DESKTOP_ENTRY}" for kind in BROWSER_TYPES]
    lines: list[str] = []
    section = None
    for line in content.splitlines():
        if line.strip().startswith("["):
            if section == DEFAULTS_SECTION:
                lines.extend(selections)
                selections = []
            section = line.strip()
        elif (
            section == DEFAULTS_SECTION
            and line.split("=", 1)[0].strip() in BROWSER_TYPES
        ):
            continue
        lines.append(line)
    if selections:
        if section != DEFAULTS_SECTION:
            lines.append(DEFAULTS_SECTION)
        lines.extend(selections)
    return "\n".join(lines) + "\n"


def browser_selected(content: str) -> bool:
    return browser_defaults(content) == content


def prerequisites() -> Path:
    if platform.system() != "Linux" or posix_uid() == 0:
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
    if session.exists() and session.read_text(encoding="utf-8") != SESSION_CONTENT:
        raise ProvisionFailure(
            "linux_desktop_session_conflict: .xsession already selects another session; "
            "preserve that customization and have the operator select XFCE deliberately"
        )
    return home


def install_root_file(content: str, path: str, mode: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as candidate:
        candidate.write(content)
        candidate.flush()
        command(["sudo", "-n", "install", "-o", "root", "-g", "root"]
                + ["-m", mode, candidate.name, path])


def provision(
    home: Path, port: int, project: str, identity: str, address: str = ANY_ADDRESS
) -> None:
    print("linux-desktop: installing XFCE and xrdp", flush=True)
    command(["sudo", "-n", "apt-get", "update"])
    packages = (
        "xfce4", "xfce4-terminal", "xrdp", "xorgxrdp", "dbus-x11",
        "python3-venv", "scrot", "xdotool", "nftables", *HELPER_PACKAGES,
    )
    command(["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive",
             "apt-get", "install", "-y", "--no-install-recommends", *packages])
    if address == ANY_ADDRESS:
        install_firewall(port, command, install_root_file)
    config_path = Path("/etc/xrdp/xrdp.ini")
    original = config_path.read_text(encoding="utf-8")
    configured = listener_config(original, port, address)
    if configured != original:
        install_root_file(configured, str(config_path), "0644")
    (home / ".xsession").write_text(SESSION_CONTENT, encoding="utf-8", newline="\n")
    (home / ".xsession").chmod(0o600)
    helpers = home / ".config/xfce4/helpers.rc"
    helpers.parent.mkdir(parents=True, exist_ok=True)
    helpers.write_text(
        helper_settings(helpers.read_text(encoding="utf-8") if helpers.exists() else ""),
        encoding="utf-8", newline="\n",
    )
    print("linux-desktop: routing web links to the identity browser", flush=True)
    entry = home / ".local/share/applications" / LAUNCHER_DESKTOP_ENTRY
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(launcher_entry(project, identity), encoding="utf-8")
    browser_helper = home / BROWSER_HELPER_PATH
    browser_helper.parent.mkdir(parents=True, exist_ok=True)
    browser_helper.write_text(BROWSER_HELPER, encoding="utf-8")
    defaults = home / ".config/mimeapps.list"
    defaults.write_text(
        browser_defaults(defaults.read_text(encoding="utf-8") if defaults.exists() else ""), encoding="utf-8", newline="\n"
    )
    command(["sudo", "-n", "usermod", "-aG", "ssl-cert", "xrdp"])
    command(["sudo", "-n", "systemctl", "enable", "--now", "xrdp", "xrdp-sesman"])
    command(["sudo", "-n", "systemctl", "restart", "xrdp"])


def selected_launcher(home: Path) -> str:
    """Prove web links open in the registered identity launcher."""
    entry = home / ".local/share/applications" / LAUNCHER_DESKTOP_ENTRY
    defaults = home / ".config/mimeapps.list"
    if not entry.is_file() or not defaults.is_file() or not browser_selected(
        defaults.read_text(encoding="utf-8")
    ):
        raise ProvisionFailure(
            "linux_desktop_default_browser_not_selected: web links bypass the identity "
            "launcher; rerun provisioning with --browser-project and --browser-identity"
        )
    lines = entry.read_text(encoding="utf-8").splitlines()
    return next((x[len("Exec="):] for x in lines if x.startswith("Exec=")), "")


def verify(home: Path, port: int = DEFAULT_RDP_PORT, address: str = ANY_ADDRESS) -> dict:
    command(["systemctl", "is-active", "xrdp", "xrdp-sesman"])
    wait_for_listener(port, address)
    if address == ANY_ADDRESS:
        prove_firewall(port, command(["sudo", "-n", "nft", "list", "ruleset"]).stdout)
    if (home / ".xsession").read_text(encoding="utf-8") != SESSION_CONTENT:
        raise ProvisionFailure(
            "linux_desktop_session_not_proved: rerun provisioning to select XFCE"
        )
    required_packages = (
        "xfce4-session", "xfce4-terminal", "xorgxrdp", "scrot", "xdotool",
        *HELPER_PACKAGES,
    )
    installed = command(
        ["dpkg-query", "-W", "-f=${db:Status-Status}\n", *required_packages]
    ).stdout.splitlines()
    if installed != ["installed"] * len(required_packages):
        raise ProvisionFailure(
            f"linux_desktop_packages_not_proved: rerun provisioning to install "
            f"{', '.join(required_packages)}"
        )
    helpers = home / ".config/xfce4/helpers.rc"
    settings = helpers.read_text(encoding="utf-8") if helpers.is_file() else ""
    if TERMINAL_SELECTION not in settings.splitlines():
        raise ProvisionFailure(
            "linux_desktop_terminal_not_selected: rerun provisioning to select xfce4-terminal"
        )
    browser_helper = home / BROWSER_HELPER_PATH
    if (
        BROWSER_SELECTION not in settings.splitlines()
        or not browser_helper.is_file()
        or browser_helper.read_text(encoding="utf-8") != BROWSER_HELPER
    ):
        raise ProvisionFailure(
            "linux_desktop_default_browser_not_selected: rerun provisioning to select "
            "the Yoke identity browser in XFCE"
        )
    chosen = selected_launcher(home)
    status = command(["passwd", "-S"]).stdout.split()
    return {
        "ok": True,
        "desktop": "XFCE",
        "default_browser": chosen,
        "rdp_listener": f"{address}:{port}",
        "login_password_set": len(status) > 1 and status[1] == "P",
        "operator_next_step": (
            "The product opens the dedicated desktop with its capability-owned secret. "
            "Authorize the operator identity with `yoke browser authorize --test-machine`; "
            "web links then open signed in through `yoke browser open`."
        ),
    }


def wait_for_listener(port: int, address: str) -> None:
    # systemctl restart returns before xrdp has opened its listening socket.
    deadline = time.monotonic() + 10
    while True:
        output = command(["ss", "-H", "-ltn", f"sport = :{port}"]).stdout
        if output.strip() or time.monotonic() >= deadline:
            prove_listener(output, port, address)
            return
        time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Readiness check only")
    parser.add_argument("--rdp-port", type=int, default=DEFAULT_RDP_PORT)
    parser.add_argument("--desktop-password-stdin", action="store_true")
    parser.add_argument("--browser-project", help="Project slug of the operator identity")
    parser.add_argument("--browser-identity", help="Operator identity name")
    args = parser.parse_args()
    if not 1 <= args.rdp_port <= 65535:
        parser.error("--rdp-port must be between 1 and 65535")
    if args.verify and args.desktop_password_stdin:
        parser.error("--verify does not accept a password or start a desktop")
    if not args.verify and not (
        args.desktop_password_stdin and args.browser_project and args.browser_identity
    ):
        parser.error(
            "provisioning requires --desktop-password-stdin from the capability store "
            "and --browser-project/--browser-identity naming the operator identity"
        )
    try:
        password = desktop_password_input() if args.desktop_password_stdin else None
        home = prerequisites()
        if not args.verify:
            provision(home, args.rdp_port, args.browser_project, args.browser_identity)
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
