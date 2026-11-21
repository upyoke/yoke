"""Provision an existing Azure Windows lab VM; no resource creation or passwords in argv."""

import argparse
import base64
from pathlib import Path
import secrets
import subprocess
import tempfile
import sys
import time

from yoke_contracts.designed_wait import announce_designed_wait
from yoke_contracts.machine_config.capability_secret_store import (
    test_machine_secret_path,
    read_test_machine_secret,
    store_test_machine_secret,
)
from yoke_harness.native_windows.transport import encoded, quote
from yoke_harness.native_windows.stdin_frame import READ_FRAME_SCRIPT
from yoke_harness.native_windows.admin import admin_script
from yoke_harness.native_windows.journal import PROGRAM, TASK
from yoke_harness.native_windows.autologon import SCRIPT as AUTOLOGON_SCRIPT
from yoke_harness.native_windows.tailnet_startup import SCRIPT as TAILNET_STARTUP_SCRIPT
from yoke_harness.native_windows.console_setup import console_settings_script
from yoke_harness.native_windows.display_geometry import console_display_task_script
from yoke_harness.native_windows.firewall import SCRIPT as RDP_FIREWALL_SCRIPT
from yoke_harness.native_windows.user_ssh import SCRIPT as USER_SSH_SCRIPT
from yoke_harness.native_windows.receipts import SETUP as RECOVERY_PATHS
from yoke_harness.native_windows.profile import (
    SCRIPT as PROFILE_SCRIPT,
    missing_password_guard,
)


BOOTSTRAP_TIMEOUT_SECONDS = 5400


def provision(
    project,
    machine,
    host,
    resource_group,
    admin_user,
    test_user,
    *,
    bootstrap_transport="azure",
):
    if bootstrap_transport not in {"azure", "ssh"}:
        raise ValueError("windows_bootstrap_transport_invalid: choose azure or ssh")
    key = test_machine_secret_path(machine, "ssh_private_key")
    public = subprocess.run(
        ["ssh-keygen", "-y", "-f", str(key)], check=True, capture_output=True, text=True
    ).stdout.strip()
    script = r"""$ErrorActionPreference='Stop'
Write-Output 'Native OpenSSH stage: capability'
$sshDir=Join-Path $env:WINDIR 'System32\OpenSSH'
if((Get-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0).State -ne 'Installed'){
 $installed=Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
 if($installed.RestartNeeded){throw 'windows_openssh_reboot_required: reboot the lab VM and rerun provisioning'}
}
Set-Service sshd -StartupType Automatic
Write-Output 'Native OpenSSH stage: configuration'
$config=Join-Path $env:ProgramData 'ssh\sshd_config'
New-Item -ItemType Directory -Force (Split-Path $config) | Out-Null
if(!(Test-Path -LiteralPath $config)){
 Copy-Item -LiteralPath "$sshDir\sshd_config_default" -Destination $config
}
$text=Get-Content -Raw $config
$text=$text -replace '(?m)^#?PasswordAuthentication\s+.*$','PasswordAuthentication no'
$text=$text -replace '(?m)^#?PubkeyAuthentication\s+.*$','PubkeyAuthentication yes'
$text=$text -replace '(?m)^AuthenticationMethods\s+.*$',''
Set-Content -LiteralPath $config -Value ("AuthenticationMethods publickey`n"+$text)
& "$sshDir\ssh-keygen.exe" -A
& "$sshDir\sshd.exe" -t -f $config
if($LASTEXITCODE){throw 'windows_sshd_config_invalid: repair the key-only configuration before starting SSH'}
Set-Content -LiteralPath "$env:ProgramData\ssh\administrators_authorized_keys" -Value PUBLIC_KEY
& icacls.exe "$env:ProgramData\ssh\administrators_authorized_keys" /inheritance:r /grant '*S-1-5-32-544:F' '*S-1-5-18:F' | Out-Null
if($LASTEXITCODE){throw 'windows_admin_key_acl_failed: repair Administrators/SYSTEM access and retry'}
Write-Output 'Native OpenSSH stage: firewall'
Get-NetFirewallRule -Name OpenSSH-Server-In-TCP,YokeQaSsh -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name YokeQaSsh -DisplayName 'Yoke QA SSH' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -Profile Any -RemoteAddress Any -ErrorAction Stop | Out-Null
$rule=Get-NetFirewallRule -PolicyStore ActiveStore -Name YokeQaSsh -ErrorAction Stop
$port=$rule | Get-NetFirewallPortFilter -ErrorAction Stop
if($rule.Enabled -ne 'True' -or $rule.Direction -ne 'Inbound' -or $rule.Action -ne 'Allow' -or $port.LocalPort -ne '22'){
 throw 'windows_admin_ssh_firewall_failed: inspect the effective YokeQaSsh firewall rule'
}
Write-Output 'Native OpenSSH stage: service'
Restart-Service sshd
Write-Output 'Native OpenSSH ready; password authentication disabled.'
""".replace("PUBLIC_KEY", quote(public))
    if bootstrap_transport == "ssh":
        announce_designed_wait(
            "Windows OpenSSH bootstrap over administrator SSH",
            max_wait_seconds=424,
            cadence="script upload and SSH command completion",
        )
        result = admin_script(key, host, admin_user, script)
        if (
            result.returncode
            or "Native OpenSSH ready; password authentication disabled."
            not in result.stdout
        ):
            raise RuntimeError(
                "windows_openssh_bootstrap_failed: inspect administrator SSH bootstrap diagnostics; "
                + (result.stderr + result.stdout)[-2000:]
            )
        print("Native OpenSSH ready; password authentication disabled.")
    else:
        with tempfile.TemporaryDirectory(prefix="yoke-windows-provision-") as temporary:
            path = Path(temporary) / "openssh.ps1"
            # Azure's RunPowerShellScript wrapper permits prompts; the child must not.
            path.write_text(
                "& powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "
                + encoded(script)
                + "\nif($LASTEXITCODE -ne 0){exit $LASTEXITCODE}\n",
                encoding="utf-8",
            )
            announce_designed_wait(
                "Azure Windows OpenSSH bootstrap",
                max_wait_seconds=BOOTSTRAP_TIMEOUT_SECONDS,
                cadence="Azure guest command completion",
            )
            deadline = time.monotonic() + BOOTSTRAP_TIMEOUT_SECONDS
            while True:
                result = subprocess.run(
                    [
                        "az",
                        "vm",
                        "run-command",
                        "invoke",
                        "--resource-group",
                        resource_group,
                        "--name",
                        machine,
                        "--command-id",
                        "RunPowerShellScript",
                        "--scripts",
                        "@" + str(path),
                        "--query",
                        "value[].message",
                        "-o",
                        "tsv",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=max(1, deadline - time.monotonic()),
                )
                if (
                    "Run command extension execution is in progress"
                    not in result.stderr
                ):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        "windows_openssh_bootstrap_busy: Azure still owns the previous guest command; wait for its completion before provisioning again"
                    )
                print(
                    "windows_openssh_bootstrap_busy: waiting for the existing Azure guest command before retrying readiness.",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(min(30, remaining))
            if (
                result.returncode
                or "Native OpenSSH ready; password authentication disabled."
                not in result.stdout
            ):
                raise RuntimeError(
                    "windows_openssh_bootstrap_failed: inspect Azure run-command diagnostics and rerun provisioning; "
                    + (result.stderr + result.stdout)[-2000:]
                )
            print("Native OpenSSH ready; password authentication disabled.")
    password = read_test_machine_secret(
        machine, "desktop_password"
    )
    if not password:
        absent = admin_script(key, host, admin_user, missing_password_guard(test_user))
        if absent.returncode or "YOKE_TEST_USER_ABSENT" not in absent.stdout:
            raise RuntimeError(
                "windows_existing_user_secret_required: verify account absence or restore its stored secret; no password was reset"
            )
        password = secrets.token_urlsafe(32) + "aA1!"
        store_test_machine_secret(
            machine, "desktop_password", password
        )
    setup = (
        r"""$ErrorActionPreference='Stop'
$name=TEST_USER
$password=[Text.Encoding]::UTF8.GetString((Read-YokeFrame))
$secure=ConvertTo-SecureString $password -AsPlainText -Force
PROFILE_CREATION
Add-LocalGroupMember -SID 'S-1-5-32-555' -Member $name -ErrorAction SilentlyContinue
if((Get-LocalGroupMember -SID 'S-1-5-32-544').Name -contains "$env:COMPUTERNAME\$name"){throw 'windows_test_user_admin: remove the test user from Administrators and retry'}
New-Item -ItemType Directory -Force "$homePath\.ssh",'C:\YokeQa\goldens' | Out-Null
USER_SSH_ACCESS
RECOVERY_PATHS
TAILNET_STARTUP
Disable-YokeTailnetTrayStartup -UserHome $homePath -UserSid $sid | ConvertTo-Json -Compress
Invoke-YokeAcl 'C:\YokeQa' /grant "${name}:(OI)(CI)M" /T
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
RDP_FIREWALL
Write-Output 'Native standard user, private golden directory and private desktop routes ready.'
""".replace("TEST_USER", quote(test_user))
        .replace("USER_SSH_ACCESS", USER_SSH_SCRIPT)
        .replace("RECOVERY_PATHS", RECOVERY_PATHS)
        .replace("TAILNET_STARTUP", TAILNET_STARTUP_SCRIPT)
        .replace("PUBLIC_KEY", quote(public))
        .replace("PROFILE_CREATION", PROFILE_SCRIPT)
        .replace("RDP_FIREWALL", RDP_FIREWALL_SCRIPT)
    )
    result = admin_script(
        key,
        host,
        admin_user,
        READ_FRAME_SCRIPT + setup + AUTOLOGON_SCRIPT + console_settings_script() + console_display_task_script(),
        input_text=password,
    )
    if result.returncode:
        # A setup command must never expose the streamed password in diagnostics.
        raise RuntimeError(
            "windows_native_provision_failed: inspect the VM administrator setup; "
            + result.stderr.replace(password, "[REDACTED]")[-1200:]
        )
    print(result.stdout.replace(password, "[REDACTED]"))
    program = base64.b64encode(PROGRAM.encode("utf-8")).decode("ascii")
    journal_setup = f"""
$ErrorActionPreference='Stop'
[IO.File]::WriteAllBytes('C:\\ProgramData\\YokeQa\\private\\machine-settings.ps1',[Convert]::FromBase64String('{program}'))
$action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -NonInteractive -File C:\\ProgramData\\YokeQa\\private\\machine-settings.ps1'
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName {quote(TASK)} -Action $action -Principal $principal -Force | Out-Null
$sid=(Get-LocalUser -Name {quote(test_user)}).SID.Value
$scheduler=New-Object -ComObject Schedule.Service
$scheduler.Connect()
$task=$scheduler.GetFolder('\\').GetTask({quote(TASK)})
$task.SetSecurityDescriptor(('D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGX;;;'+$sid+')'),0)
Write-Output 'Native QA recovery task ready.'
"""
    installed = admin_script(key, host, admin_user, journal_setup)
    if installed.returncode:
        raise RuntimeError(
            "windows_journal_provision_failed: repair the fixed recovery task and its ACL; "
            + installed.stderr[-1200:]
        )
    print(installed.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "machine", "host", "resource-group"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--admin-user", default="yokeadmin")
    parser.add_argument("--test-user", default="yokeqa")
    parser.add_argument(
        "--bootstrap-transport", choices=("azure", "ssh"), default="azure"
    )
    args = parser.parse_args()
    try:
        provision(
            args.project,
            args.machine,
            args.host,
            args.resource_group,
            args.admin_user,
            args.test_user,
            bootstrap_transport=args.bootstrap_transport,
        )
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(
            str(exc) + "; repair the named provisioning step and rerun.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
