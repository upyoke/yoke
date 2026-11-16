"""Provision an existing Azure Windows lab VM; no resource creation or passwords in argv."""

import argparse
import base64
from pathlib import Path
import secrets
import subprocess
import tempfile
import sys

from yoke_contracts.machine_config.capability_secret_store import (
    machine_capability_secret_path,
    read_machine_capability_secret,
    store_machine_capability_secret,
)
from yoke_harness.native_windows.transport import encoded, quote
from yoke_harness.native_windows.journal import PROGRAM, TASK
from yoke_harness.native_windows.autologon import SCRIPT as AUTOLOGON_SCRIPT


def admin_script(key, host, user, script, *, input_text=None):
    path = r"C:\ProgramData\YokeQaProvision.ps1"
    ssh = [
        "ssh",
        "-i",
        str(key),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        f"{user}@{host}",
    ]
    write = f"[IO.File]::WriteAllBytes({quote(path)},[Convert]::FromBase64String([Console]::In.ReadToEnd()))"
    uploaded = subprocess.run(
        [
            *ssh,
            "powershell.exe -NoProfile -NonInteractive -EncodedCommand "
            + encoded(write),
        ],
        input=base64.b64encode(script.encode("utf-8-sig")).decode("ascii"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if uploaded.returncode:
        raise RuntimeError(
            "windows_admin_script_upload_failed: verify administrator SSH key access; "
            + uploaded.stderr[-800:]
        )
    return subprocess.run(
        [*ssh, "powershell.exe -NoProfile -NonInteractive -File " + path],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=300,
    )


def provision(project, machine, host, resource_group, admin_user, test_user):
    key = machine_capability_secret_path(project, "test-machine", "ssh_private_key")
    public = subprocess.run(
        ["ssh-keygen", "-y", "-f", str(key)], check=True, capture_output=True, text=True
    ).stdout.strip()
    script = r"""$ErrorActionPreference='Stop'
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
Set-Service sshd -StartupType Automatic
$config=Join-Path $env:ProgramData 'ssh\sshd_config'
New-Item -ItemType Directory -Force (Split-Path $config) | Out-Null
if(!(Test-Path -LiteralPath $config)){
 Copy-Item -LiteralPath "$env:WINDIR\System32\OpenSSH\sshd_config_default" -Destination $config
}
$text=Get-Content -Raw $config
$text=$text -replace '(?m)^#?PasswordAuthentication\s+.*$','PasswordAuthentication no'
$text=$text -replace '(?m)^#?PubkeyAuthentication\s+.*$','PubkeyAuthentication yes'
Set-Content -LiteralPath $config -Value ("AuthenticationMethods publickey`n"+$text)
Set-Content -LiteralPath "$env:ProgramData\ssh\administrators_authorized_keys" -Value PUBLIC_KEY
& icacls.exe "$env:ProgramData\ssh\administrators_authorized_keys" /inheritance:r /grant '*S-1-5-32-544:F' '*S-1-5-18:F' | Out-Null
if($LASTEXITCODE){throw 'windows_admin_key_acl_failed: repair Administrators/SYSTEM access and retry'}
Get-NetFirewallRule -Name OpenSSH-Server-In-TCP -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name YokeQaSsh -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -Profile Any -RemoteAddress Any -ErrorAction SilentlyContinue | Out-Null
Restart-Service sshd
Write-Output 'Native OpenSSH ready; password authentication disabled.'
""".replace("PUBLIC_KEY", quote(public))
    with tempfile.TemporaryDirectory(prefix="yoke-windows-provision-") as temporary:
        path = Path(temporary) / "openssh.ps1"
        path.write_text(script)
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
            timeout=900,
        )
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
    password = read_machine_capability_secret(
        project, "test-machine:" + machine, "desktop_password"
    )
    if not password:
        password = secrets.token_urlsafe(32) + "aA1!"
        store_machine_capability_secret(
            project, "test-machine:" + machine, "desktop_password", password
        )
    setup = r"""$ErrorActionPreference='Stop'
$name=TEST_USER
$password=[Console]::In.ReadToEnd().Trim()
$secure=ConvertTo-SecureString $password -AsPlainText -Force
if(Get-LocalUser -Name $name -ErrorAction SilentlyContinue){Set-LocalUser -Name $name -Password $secure}
else {New-LocalUser -Name $name -Password $secure -PasswordNeverExpires | Out-Null}
Add-LocalGroupMember -SID 'S-1-5-32-555' -Member $name -ErrorAction SilentlyContinue
if((Get-LocalGroupMember -SID 'S-1-5-32-544').Name -contains "$env:COMPUTERNAME\$name"){throw 'windows_test_user_admin: remove the test user from Administrators and retry'}
# Create its profile without an interactive password exchange.
$credential=[PSCredential]::new("$env:COMPUTERNAME\$name",$secure)
$p=Start-Process powershell.exe -Credential $credential -LoadUserProfile -ArgumentList '-NoProfile -Command exit' -PassThru -Wait
if($p.ExitCode){throw 'windows_profile_creation_failed: inspect the standard test account'}
$homePath="C:\Users\$name"
New-Item -ItemType Directory -Force "$homePath\.ssh",'C:\YokeQa\goldens','C:\ProgramData\YokeQa\requests','C:\ProgramData\YokeQa\private' | Out-Null
Set-Content -LiteralPath "$homePath\.ssh\authorized_keys" -Value PUBLIC_KEY
& icacls.exe "$homePath\.ssh" /inheritance:r /grant "${name}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /T | Out-Null
& icacls.exe 'C:\YokeQa' /grant "${name}:(OI)(CI)M" /T | Out-Null
& icacls.exe 'C:\ProgramData\YokeQa' /inheritance:r /grant '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "${name}:(OI)(CI)RX" | Out-Null
& icacls.exe 'C:\ProgramData\YokeQa\private' /inheritance:r /grant '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
& icacls.exe 'C:\ProgramData\YokeQa\private' /inheritance:r /grant '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
& icacls.exe 'C:\ProgramData\YokeQa\requests' /grant "${name}:(OI)(CI)M" | Out-Null
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
# RDP is reachable only by SSH local forwarding, including on the guest.
Get-NetFirewallRule -DisplayGroup 'Remote Desktop' | Disable-NetFirewallRule
New-NetFirewallRule -Name YokeQaRdpLoopback -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3389 -RemoteAddress 127.0.0.1,::1 -Profile Any -ErrorAction SilentlyContinue | Out-Null
Write-Output 'Native standard user, private golden directory and SSH-only desktop route ready.'
""".replace("TEST_USER", quote(test_user)).replace("PUBLIC_KEY", quote(public))
    result = admin_script(
        key, host, admin_user, setup + AUTOLOGON_SCRIPT, input_text=password
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
    args = parser.parse_args()
    try:
        provision(
            args.project,
            args.machine,
            args.host,
            args.resource_group,
            args.admin_user,
            args.test_user,
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
