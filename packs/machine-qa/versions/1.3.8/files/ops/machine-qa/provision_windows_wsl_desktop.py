"""Prepare a loopback-only XFCE desktop in the Windows test user's WSL home."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess

import provision_linux_desktop as desktop

DEFAULT_WSL_RDP_PORT = 3390


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
    args = parser.parse_args()
    if not 1 <= args.rdp_port <= 65535 or args.rdp_port == desktop.DEFAULT_RDP_PORT:
        parser.error("--rdp-port needs a valid port separate from native Windows RDP")
    try:
        facts = windows_facts()
        home = desktop.prerequisites()
        if not args.verify:
            desktop.provision(home, args.rdp_port)
        result = desktop.verify(home, args.rdp_port)
        prove_windows_localhost(args.rdp_port)
        result.update(
            facts,
            display_route="WSL XFCE through Windows localhost RDP",
            operator_next_step=(
                "Keep the registered Windows RDP desktop open, run "
                f"mstsc.exe /v:127.0.0.1:{args.rdp_port}, and personally log into "
                "the dedicated Linux test user. Prove candidate Chromium renders "
                "in its XFCE terminal before personal application sign-in."
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
