"""Prepare a WSL XFCE desktop the Windows host exposes only on its tailnet.

xrdp listens on WSL loopback, which Windows localhost forwarding carries to
127.0.0.1 on the host. A port proxy on the host's Tailscale address forwards
to it, and one firewall rule admits that port only on the Tailscale interface.
The proxy binds only while that address exists, and Windows starts IP Helper
before Tailscale at boot, so a SYSTEM startup task rebinds it once Tailscale is up.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import platform
import re
import subprocess

import provision_linux_desktop as desktop
from linux_desktop_listener import LOOPBACK

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
    if Path("/proc/1/comm").read_text(encoding="utf-8").strip() != "systemd":
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
            "forwarding; do not open a public listener"
        ) from None


TAILNET_RULE = "YokeWslDesktopTailnet"
# Runs at every boot: wait for the Tailscale address, then restart IP Helper
# so the port proxy binds to it if it is not already listening there.
REBIND_SCRIPT = r"""$port={port}
function Listening($ip){{ @(Get-NetTCPConnection -State Listen -LocalAddress $ip -LocalPort $port -ErrorAction SilentlyContinue).Count -gt 0 }}
for($i=0;$i -lt 120;$i++){{
 $a=@(Get-NetIPAddress -InterfaceAlias Tailscale -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {{$_.IPAddress -like '100.*'}})
 if($a.Count -eq 1){{
  if(Listening $a[0].IPAddress){{exit 0}}
  Restart-Service iphlpsvc -Force; Start-Sleep 5
  if(Listening $a[0].IPAddress){{exit 0}}
 }}
 Start-Sleep 5
}}
exit 1
"""


def rebind_argument(port: int) -> str:
    """The startup task's powershell.exe arguments, compared verbatim on verify."""
    encoded = base64.b64encode(REBIND_SCRIPT.format(port=port).encode("utf-16-le"))
    return "-NoProfile -NonInteractive -EncodedCommand " + encoded.decode("ascii")


TAILNET_SCRIPT = r"""
$ErrorActionPreference='Stop'
$port={port}
$address=@(Get-NetIPAddress -InterfaceAlias Tailscale -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {{$_.IPAddress -like '100.*'}})
if($address.Count -ne 1){{throw 'windows_wsl_tailnet_address_missing: start Tailscale on the Windows host and join the tailnet, then rerun'}}
$ip=$address[0].IPAddress
if('{mode}' -eq 'apply'){{
 foreach($line in @(netsh interface portproxy show v4tov4 | Select-String "\s$port\s")){{
  $listen=($line.ToString().Trim() -split '\s+')[0]
  netsh interface portproxy delete v4tov4 listenaddress=$listen listenport=$port | Out-Null
 }}
 netsh interface portproxy add v4tov4 listenaddress=$ip listenport=$port connectaddress=127.0.0.1 connectport=$port | Out-Null
 Get-NetFirewallRule -Name {rule} -ErrorAction SilentlyContinue | Remove-NetFirewallRule
 New-NetFirewallRule -Name {rule} -DisplayName 'Yoke WSL desktop (Tailscale only)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -InterfaceAlias Tailscale -Profile Any | Out-Null
 $principal=New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest
 Register-ScheduledTask -TaskName {rule} -Action (New-ScheduledTaskAction -Execute powershell.exe -Argument '{rebind}') -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $principal -Force | Out-Null
}}
$task=Get-ScheduledTask -TaskName {rule} -ErrorAction SilentlyContinue
if(!$task -or $task.State -eq 'Disabled' -or $task.Principal.UserId -notin @('SYSTEM','NT AUTHORITY\SYSTEM') -or @($task.Triggers | Where-Object {{$_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger'}}).Count -ne 1 -or @($task.Actions).Count -ne 1 -or $task.Actions[0].Arguments -ne '{rebind}'){{throw 'windows_wsl_tailnet_rebind_not_proved: startup task {rule} must rebind the port proxy once Tailscale is up; rerun Pack provisioning'}}
$proxies=@(netsh interface portproxy show v4tov4 | Select-String "\s$port\s" | ForEach-Object {{,($_.ToString().Trim() -split '\s+')}})
if($proxies.Count -ne 1 -or $proxies[0][0] -ne $ip -or $proxies[0][2] -ne '127.0.0.1' -or $proxies[0][3] -ne "$port"){{throw "windows_wsl_tailnet_proxy_not_proved: one port proxy must forward $ip`:$port to 127.0.0.1`:$port; rerun Pack provisioning"}}
$rule=Get-NetFirewallRule -Name {rule} -ErrorAction SilentlyContinue
$interfaces=@($rule | Get-NetFirewallInterfaceFilter | ForEach-Object InterfaceAlias)
if(!$rule -or $rule.Enabled -ne 'True' -or $interfaces.Count -ne 1 -or $interfaces[0] -ne 'Tailscale'){{throw 'windows_wsl_tailnet_firewall_not_proved: rule {rule} must admit the port only on the Tailscale interface; rerun Pack provisioning'}}
$client=[Net.Sockets.TcpClient]::new()
try{{ if(-not $client.ConnectAsync($ip,$port).Wait(5000) -or -not $client.Connected){{throw "windows_wsl_tailnet_unreachable: $ip`:$port did not accept; run Start-ScheduledTask {rule} as administrator, then inspect the IP Helper service and the port proxy"}} }} finally {{ $client.Dispose() }}
Write-Output $ip
"""


def expose_on_tailnet(port: int, *, verify_only: bool) -> str:
    """Return the tailnet address that now reaches the WSL desktop."""
    script = TAILNET_SCRIPT.format(
        port=port,
        rule=TAILNET_RULE,
        mode="verify" if verify_only else "apply",
        rebind=rebind_argument(port),
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        text=True,
        capture_output=True,
        timeout=120,
    )
    output = (result.stdout + result.stderr).replace("\x00", "")
    if result.returncode:
        named = re.search(r"windows_wsl_tailnet_[a-z_]+:[^\r\n]*", output)
        raise desktop.ProvisionFailure(
            named[0]
            if named
            else "windows_wsl_tailnet_failed: run provisioning from an administrator "
            "Windows session and rerun"
        )
    return result.stdout.replace("\x00", "").strip().splitlines()[-1]


def configure_windows_console(password: str) -> None:
    """Apply the native console baseline to the account owning this distro."""
    from autologon import SCRIPT
    from console_setup import VALIDATE_ACCOUNT_PASSWORD, console_settings_script
    from stdin_frame import READ_FRAME_SCRIPT, frame_bytes

    script = (
        "$ErrorActionPreference='Stop'; $name=$env:USERNAME\n"
        + READ_FRAME_SCRIPT
        + "$password=[Text.Encoding]::UTF8.GetString((Read-YokeFrame))\n"
        + VALIDATE_ACCOUNT_PASSWORD
        + SCRIPT
        + console_settings_script()
    )
    argv = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
        base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
    ]
    try:
        result = subprocess.run(
            argv, input=frame_bytes(password.encode()), capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise desktop.ProvisionFailure(
            "windows_console_provision_timeout: inspect Task Scheduler and rerun as the Windows SSH administrator"
        ) from None
    if result.returncode:
        raise desktop.ProvisionFailure(
            "windows_console_provision_failed: verify Windows administrator permissions and the account profile, then rerun; "
            + result.stderr.replace(password, "[REDACTED]")[-1000:]
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Readiness check only")
    parser.add_argument("--rdp-port", type=int, default=DEFAULT_WSL_RDP_PORT)
    parser.add_argument("--desktop-password-stdin", action="store_true")
    parser.add_argument("--browser-project", help="Project slug of the operator identity")
    parser.add_argument("--browser-identity", help="Operator identity name")
    args = parser.parse_args()
    if not 1 <= args.rdp_port <= 65535 or args.rdp_port == desktop.DEFAULT_RDP_PORT:
        parser.error("--rdp-port needs a valid port separate from native Windows RDP")
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
        password = (
            desktop.desktop_password_input() if args.desktop_password_stdin else None
        )
        facts = windows_facts()
        home = desktop.prerequisites()
        lifetime = configure_instance_lifetime(verify_only=args.verify)
        if not args.verify:
            desktop.provision(
                home, args.rdp_port, args.browser_project, args.browser_identity, LOOPBACK
            )
        result = desktop.verify(home, args.rdp_port, LOOPBACK)
        prove_windows_localhost(args.rdp_port)
        tailnet_address = expose_on_tailnet(args.rdp_port, verify_only=args.verify)
        if password is not None:
            configure_windows_console(password)
            desktop.set_desktop_password(password)
            result["login_password_set"] = True
        result["desktop_session"] = "xfce_not_started"
        result["windows_console_reboot_required"] = password is not None
        result.update(
            facts,
            wsl_lifetime=lifetime,
            display_route="WSL XFCE through Windows localhost RDP",
            tailnet_listener=f"{tailnet_address}:{args.rdp_port}",
            operator_next_step=(
                "The product opens WSL XFCE with its capability-owned secret. "
                "Authorize the operator identity with `yoke browser authorize "
                "--test-machine`; web links then open signed in through `yoke browser open`."
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
