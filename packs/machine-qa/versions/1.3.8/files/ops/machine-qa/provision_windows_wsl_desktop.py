"""Prepare a loopback-only XFCE desktop in the Windows test user's WSL home."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import re
import subprocess

import provision_linux_desktop as desktop

DEFAULT_WSL_RDP_PORT = 3390
SUPPORTED_WSL_VERSION = (3, 0, 1)
INSTANCE_IDLE_TIMEOUT = -1


def persistent_instance_config(content: str) -> str:
    """Change only the distro lifetime setting, preserving other INI content."""
    prefix = "\ufeff" if content.startswith("\ufeff") else ""
    content = content.removeprefix(prefix) if prefix else content
    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.splitlines(keepends=True)
    general = []
    settings = []
    section = ""
    insert_at = len(lines)
    for index, line in enumerate(lines):
        header = re.match(r"\s*\[([^]]+)\]", line)
        if header:
            if section == "general":
                insert_at = index
            section = header[1].strip().casefold()
            if section == "general":
                general.append(index)
        elif section == "general" and re.match(
            r"\s*instanceIdleTimeout\s*=", line, re.IGNORECASE
        ):
            settings.append(index)
    if len(general) > 1 or len(settings) > 1:
        raise desktop.ProvisionFailure("windows_wsl_lifetime_config_ambiguous")
    if settings:
        index = settings[0]
        line = lines[index]
        value = re.split(r"[#;]", line.split("=", 1)[1], maxsplit=1)[0].strip()
        if value == str(INSTANCE_IDLE_TIMEOUT):
            return prefix + content
        comment = re.search(r"[#;][^\r\n]*", line)
        suffix = f" {comment[0]}" if comment else ""
        ending = newline if line.endswith("\n") else ""
        key = line.split("=", 1)[0]
        lines[index] = f"{key}={INSTANCE_IDLE_TIMEOUT}{suffix}{ending}"
    else:
        if insert_at and not lines[insert_at - 1].endswith("\n"):
            lines[insert_at - 1] += newline
        setting = f"instanceIdleTimeout={INSTANCE_IDLE_TIMEOUT}{newline}"
        lines.insert(insert_at, setting if general else f"[general]{newline}{setting}")
    return prefix + "".join(lines)


def configure_instance_lifetime(*, verify_only: bool) -> dict:
    """Own persistent setup under the Windows account that owns this WSL distro."""
    profile = (
        desktop.command(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Environment]::GetFolderPath('UserProfile') | ConvertTo-Json -Compress",
            ]
        )
        .stdout.replace("\x00", "")
        .strip()
    )
    root = Path(desktop.command(["wslpath", "-u", json.loads(profile)]).stdout.strip())
    config = root / ".wslconfig"
    if not root.is_absolute() or not root.is_dir() or config.is_symlink():
        raise desktop.ProvisionFailure("windows_wsl_lifetime_path_unsafe")
    if config.exists() and (
        not config.is_file() or config.stat().st_size > 1024 * 1024
    ):
        raise desktop.ProvisionFailure("windows_wsl_lifetime_config_unsafe")
    original = config.read_bytes().decode("utf-8") if config.exists() else ""
    configured = persistent_instance_config(original)
    changed = configured != original
    if verify_only and changed:
        raise desktop.ProvisionFailure(
            "windows_wsl_lifetime_not_configured: rerun Pack provisioning, then restart WSL"
        )
    if changed:
        # Updating in place retains an existing Windows file's ownership and ACL.
        config.write_text(configured, encoding="utf-8", newline="")
    return {
        "instance_idle_timeout": INSTANCE_IDLE_TIMEOUT,
        "configuration_changed": changed,
        "restart_required": changed,
        "persistence_proved": False,
    }


def windows_facts() -> dict:
    if "microsoft" not in platform.release().lower():
        raise desktop.ProvisionFailure(
            "windows_wsl_required: run inside the registered Windows user's WSL2 Ubuntu"
        )
    if Path("/proc/1/comm").read_text().strip() != "systemd":
        raise desktop.ProvisionFailure(
            "windows_wsl_systemd_required: have the operator enable the declared "
            "systemd prerequisite and reopen WSL before rerunning"
        )
    operating_system = (
        desktop.command(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber | ConvertTo-Json -Compress",
            ]
        )
        .stdout.replace("\x00", "")
        .strip()
    )
    wsl = desktop.command(["wsl.exe", "--version"]).stdout.replace("\x00", "").strip()
    version = re.search(r"(\d+)\.(\d+)\.(\d+)", wsl)
    if version is None or tuple(map(int, version.groups())) < SUPPORTED_WSL_VERSION:
        raise desktop.ProvisionFailure(
            "windows_wsl_version_unsupported: Pack requires WSL3.0.1 or newer"
        )
    return {"windows": json.loads(operating_system), "wsl_version": wsl}


def prove_windows_localhost(port: int) -> None:
    try:
        desktop.command(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"$client = [Net.Sockets.TcpClient]::new(); try {{ $attempt = $client.ConnectAsync('127.0.0.1', {port}); if (-not $attempt.Wait(5000) -or -not $client.Connected) {{ exit 1 }} }} finally {{ $client.Dispose() }}",
            ]
        )
    except desktop.ProvisionFailure:
        raise desktop.ProvisionFailure(
            "windows_wsl_localhost_unavailable: inspect the existing WSL localhost "
            "forwarding; do not open a public listener or change Windows firewall settings"
        ) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Readiness check only")
    parser.add_argument("--rdp-port", type=int, default=DEFAULT_WSL_RDP_PORT)
    parser.add_argument("--desktop-password-stdin", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.rdp_port <= 65535 or args.rdp_port == desktop.DEFAULT_RDP_PORT:
        parser.error("--rdp-port needs a valid port separate from native Windows RDP")
    if args.verify and args.desktop_password_stdin:
        parser.error("--verify does not accept a password or start a desktop")
    if not args.verify and not args.desktop_password_stdin:
        parser.error(
            "provisioning requires --desktop-password-stdin from the capability store"
        )
    try:
        password = (
            desktop.desktop_password_input() if args.desktop_password_stdin else None
        )
        facts = windows_facts()
        home = desktop.prerequisites()
        lifetime = configure_instance_lifetime(verify_only=args.verify)
        if not args.verify:
            desktop.provision(home, args.rdp_port)
        result = desktop.verify(home, args.rdp_port)
        prove_windows_localhost(args.rdp_port)
        if password is not None:
            desktop.set_desktop_password(password)
            result["login_password_set"] = True
        result["desktop_session"] = "not_started"
        result.update(
            facts,
            wsl_lifetime=lifetime,
            display_route="WSL XFCE through Windows localhost RDP",
            operator_next_step=(
                "The product opens WSL XFCE with its capability-owned secret. "
                "Prove candidate Chromium renders there, then request only personal application sign-in."
            ),
            headed_application_proved=False,
        )
        print(json.dumps(result), flush=True)
        return 0
    except (
        desktop.ProvisionFailure,
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"windows_wsl_desktop_not_ready: {exc}; inspect and rerun", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
