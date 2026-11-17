"""Run complete guest provisioning on a disposable GitHub Windows runner."""

import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import time
from uuid import uuid4

import pytest

from runtime.api.domain.native_windows_fixture_cleanup import AUTOLOGON_CLEARED_SCRIPT
from runtime.api.domain.native_windows_fixture_tasks import verify_standard_task_operations
from runtime.api.domain.native_windows_fixture_upload import chunk_probe
from yoke_harness.native_windows import provision
from yoke_harness.native_windows.autologon import SCRIPT as AUTOLOGON_SCRIPT
from yoke_harness.native_windows.firewall import SCRIPT as FIREWALL_SCRIPT
from yoke_harness.native_windows.transport import WindowsTransport, encoded, quote

pytestmark = pytest.mark.windows


def powershell(script, directory, timeout=300):
    path = directory / (uuid4().hex + ".ps1")
    path.write_text("$ErrorActionPreference='Stop'\n" + script, encoding="utf-8-sig")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(path)],
        capture_output=True, text=True, timeout=timeout,
    )


@pytest.mark.windows_only(reason='requires native Windows PowerShell')
def test_real_chunk_append_rejects_wrong_offset_and_preserves_prefix(tmp_path):
    from yoke_harness.native_windows.stdin_frame import upload_received

    target = tmp_path / "chunks.bin"
    payload = b"first chunk" * 100
    for offset, chunk in ((0, payload), (len(payload), b"second chunk")):
        result = chunk_probe(target, chunk, offset)
        expected = payload if offset == 0 else payload + chunk
        assert upload_received(result, expected), result.stderr
        assert target.read_bytes() == expected
    for offset in (0, 1):
        result = chunk_probe(target, b"bad", offset)
        assert result.returncode != 0
        assert target.read_bytes() == expected


@pytest.mark.skipif(
    os.environ.get("YOKE_NATIVE_WINDOWS_PROVISIONING") != "1",
    reason="changes machine provisioning only on a disposable GitHub Windows runner",
)
def test_complete_guest_provisioning_and_real_ssh_rdp_forward(monkeypatch, tmp_path, capsys):
    # Only cloud transport/custody are substituted. Every guest script executes
    # unchanged; account/profile, firewall, sshd, LSA and task APIs are real.
    assert os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    client = os.environ["YOKE_NATIVE_WINDOWS_SSH_CLIENT"]
    directory = (
        Path(os.environ["WINDIR"]) / "System32/OpenSSH" if client == "windows"
        else Path(os.environ["ProgramFiles"]) / "Git/usr/bin"
    )
    assert (directory / "ssh.exe").is_file(), "declared SSH client missing"
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ["PATH"])
    with capsys.disabled():
        print("SSH_CLIENT", client, shutil.which("ssh"))
    name = "yq" + uuid4().hex[:14]
    key = tmp_path / "key"
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    identity = powershell("[Environment]::UserName", tmp_path)
    assert identity.returncode == 0, identity.stderr
    admin = identity.stdout.strip()
    custody = {}
    monkeypatch.setattr(provision, "test_machine_secret_path", lambda *a: key)
    monkeypatch.setattr(provision, "read_test_machine_secret", lambda *a: custody.get("password"))
    monkeypatch.setattr(provision, "store_test_machine_secret", lambda *a: custody.update(password=a[-1]))
    actual_admin_script = provision.admin_script
    stages = []

    def guest(key, host, user, script, **kwargs):
        stages.append(script)
        if len(stages) == 1:
            # Equivalent to the Azure guest bootstrap, without Azure or mocks
            # of any PowerShell command. Later stages use real framed SSH.
            return powershell(script, tmp_path, timeout=900)
        try:
            result = actual_admin_script(key, host, user, script, **kwargs)
        except subprocess.TimeoutExpired:
            diagnostic = powershell(
                "Get-Service sshd | Format-List Name,Status; "
                "Get-NetTCPConnection -LocalPort 22 -ErrorAction SilentlyContinue | Format-List State,LocalAddress; "
                "Get-ChildItem 'C:\\ProgramData\\YokeQaProvision-*.ps1' -ErrorAction SilentlyContinue | Format-List Length,LastWriteTime; "
                "Get-WinEvent -LogName OpenSSH/Operational -MaxEvents 15 -ErrorAction SilentlyContinue | Select-Object TimeCreated,Message | Format-List",
                tmp_path,
            )
            with capsys.disabled():
                print(diagnostic.stdout)
                print(diagnostic.stderr)
            raise RuntimeError("Real SSH guest stage timed out; inspect OpenSSH diagnostics") from None

        if result.returncode:
            import re

            match = re.search(r"inbound allow rule\s+([^;\s]+)", result.stderr)
            if match:
                diagnostic = powershell(
                    "$r=Get-NetFirewallRule -PolicyStore ActiveStore -Name " + quote(match[1])
                    + "; $r | Format-List *; "
                    + "; ".join("$r | " + command + " | Format-List *" for command in (
                        "Get-NetFirewallApplicationFilter", "Get-NetFirewallServiceFilter",
                        "Get-NetFirewallPortFilter", "Get-NetFirewallInterfaceFilter",
                        "Get-NetFirewallInterfaceTypeFilter", "Get-NetFirewallAddressFilter",
                        "Get-NetFirewallSecurityFilter",
                    )), tmp_path,
                )
                with capsys.disabled():
                    print(diagnostic.stdout)
                    print(diagnostic.stderr)
        return result

    monkeypatch.setattr(provision, "admin_script", guest)
    ssh = ["ssh", "-F", "none", "-i", str(key), "-o", "BatchMode=yes",
           "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15"]
    tunnel = None
    try:
        provision.provision("fixture", "fixture", "127.0.0.1", "fixture", admin, name,
                            bootstrap_transport="ssh")
        output = capsys.readouterr().out
        for receipt in (
            "Native OpenSSH ready; password authentication disabled.",
            "Native standard user, private golden directory and SSH-only desktop route ready.",
            "Native QA recovery task ready.",
        ):
            assert receipt in output
        assert len(stages) == 4  # bootstrap, absent-user guard, setup, recovery task
        for user, expected in ((admin, "$true"), (name, "$false")):
            script = (
                "$ErrorActionPreference='Stop'; $id=[Security.Principal.WindowsIdentity]::GetCurrent(); "
                f"$expected=(Get-LocalUser -Name {quote(user)}).SID.Value; "
                "if($id.User.Value -ne $expected){throw 'wrong SSH token SID'}; "
                "$isAdmin=([Security.Principal.WindowsPrincipal]::new($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator); "
                f"if($isAdmin -ne {expected}){{throw 'wrong SSH privilege'}}; 'TOKEN_OK'"
            )
            result = subprocess.run(
                [*ssh, user + "@127.0.0.1", "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded(script)],
                capture_output=True, text=True, timeout=45,
            )
            if result.returncode:
                diagnostic = powershell(
                    "$u=Get-LocalUser -Name " + quote(user)
                    + "; $p=Get-ItemProperty -LiteralPath ('HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\'+$u.SID.Value); "
                    + "$u | Format-List Name,Enabled,SID; $p | Format-List ProfileImagePath; "
                    + "$h=$p.ProfileImagePath; Get-Acl $h,(Join-Path $h '.ssh'),(Join-Path $h '.ssh\\authorized_keys') | Format-List Path,Owner,Sddl; "
                    + "Get-Content 'C:\\ProgramData\\ssh\\sshd_config'; "
                    + "& ($env:WINDIR+'\\System32\\OpenSSH\\sshd.exe') -T -C " + quote("user=" + user + ",host=localhost,addr=127.0.0.1")
                    + "; Get-WinEvent -LogName OpenSSH/Operational -MaxEvents 20 -ErrorAction SilentlyContinue | Select-Object TimeCreated,Message | Format-List",
                    tmp_path,
                )
                with capsys.disabled():
                    print(diagnostic.stdout)
                    print(diagnostic.stderr)
            assert result.returncode == 0, result.stderr
            assert "TOKEN_OK" in result.stdout
        # Exercise the production facts probe, not only the independent token
        # assertion: standard SSH users cannot query Win32_OperatingSystem CIM.
        transport = WindowsTransport(
            settings={"os": "windows", "host": "127.0.0.1", "user": name},
            key_path=key, secret_values=(custody["password"],),
        )
        assert transport.windows_facts["admin"] is False
        assert transport.windows_facts["user"].split("\\")[-1].lower() == name
        assert transport.windows_facts["build"].isdigit()
        assert transport.home.lower().endswith("\\" + name)
        verify_standard_task_operations(
            {"os": "windows", "host": "127.0.0.1", "user": name}, key, custody["password"],
        )
        checks = rf"""
$u=Get-LocalUser -Name '{name}'
$p=Get-ItemProperty -LiteralPath ('HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\'+$u.SID.Value)
$acl=Get-Acl (Join-Path $p.ProfileImagePath '.ssh\authorized_keys')
$rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if($rules.Count -ne 3 -or @($rules | Where-Object {{$_.IdentityReference.Value -notin @($u.SID.Value,'S-1-5-18','S-1-5-32-544') -or $_.AccessControlType -ne 'Allow'}}).Count){{throw 'unexpected authorized_keys DACL'}}
$g=Get-LocalGroup -Name 'OpenSSH Users' -ErrorAction SilentlyContinue
if($g -and @(Get-LocalGroupMember -Group $g.Name).SID.Value -notcontains $u.SID.Value){{throw 'SSH group membership missing'}}
if(!(Test-Path -LiteralPath (Join-Path $p.ProfileImagePath 'NTUSER.DAT'))){{throw 'profile hive missing'}}
$task=Get-ScheduledTask -TaskName YokeQaMachineSettings
if($task.Principal.UserId -notin @('SYSTEM','S-1-5-18')){{throw 'recovery task is not SYSTEM'}}
if(!(Test-Path 'C:\ProgramData\YokeQa\private\machine-settings.ps1')){{throw 'recovery program missing'}}
if(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name DefaultPassword -ErrorAction SilentlyContinue){{throw 'plaintext autologon password'}}
if(Get-ChildItem 'C:\ProgramData\YokeQaProvision-*.ps1' -ErrorAction SilentlyContinue){{throw 'owned upload staging remains'}}
'GUEST_SETUP_OK'
"""
        verified = powershell(checks, tmp_path)
        assert verified.returncode == 0, verified.stderr
        assert "GUEST_SETUP_OK" in verified.stdout
        # A genuinely unrestricted RDP rule must still fail closed. The
        # built-in kernel/Wi-Fi rule is unrelated to svchost's RDP listener.
        rule = "YokeFixtureRdp" + uuid4().hex
        rejected = powershell(
            f"New-NetFirewallRule -Name '{rule}' -DisplayName 'owned RDP fixture' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3389 -Program Any -Service Any | Out-Null; try {{\n"
            + FIREWALL_SCRIPT + f"\n}} finally {{Remove-NetFirewallRule -Name '{rule}'}}",
            tmp_path,
        )
        assert rejected.returncode != 0 and rule in rejected.stderr
        # Reproduce the protected empty file DACL left by partial provisioning.
        import json

        partial = powershell(rf"""
$u=Get-LocalUser -Name '{name}'
$p=Get-ItemProperty -LiteralPath ('HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\'+$u.SID.Value)
$key=Join-Path $p.ProfileImagePath '.ssh\authorized_keys'
Set-Content -LiteralPath $key -Value 'owned-stale-key' -Encoding ascii
$acl=Get-Acl -LiteralPath $key
$acl.SetAccessRuleProtection($true,$false)
foreach($rule in @($acl.Access)){{$acl.RemoveAccessRuleSpecific($rule)}}
Set-Acl -LiteralPath $key -AclObject $acl
$actual=Get-Acl -LiteralPath $key
if(!$actual.AreAccessRulesProtected -or @($actual.Access).Count){{throw 'empty DACL fixture not established'}}
@{{sid=$u.SID.Value;passwordSet=$u.PasswordLastSet.ToFileTimeUtc();profile=$p.ProfileImagePath}} | ConvertTo-Json -Compress
""", tmp_path)
        assert partial.returncode == 0, partial.stderr
        before = json.loads(partial.stdout)
        saved_password = custody["password"]
        # Retry the entire unchanged provisioner through administrator SSH.
        provision.provision("fixture", "fixture", "127.0.0.1", "fixture", admin, name,
                            bootstrap_transport="ssh")
        capsys.readouterr()
        assert custody["password"] == saved_password
        repaired = powershell(checks + rf"""
if((Get-Content -LiteralPath (Join-Path $p.ProfileImagePath '.ssh\authorized_keys') -Raw).Trim() -cne {quote(key.with_suffix('.pub').read_text().strip())}){{throw 'public key content not repaired'}}
@{{sid=$u.SID.Value;passwordSet=$u.PasswordLastSet.ToFileTimeUtc();profile=$p.ProfileImagePath}} | ConvertTo-Json -Compress
""", tmp_path)
        assert repaired.returncode == 0, repaired.stderr
        assert json.loads(repaired.stdout.splitlines()[-1]) == before
        probe = subprocess.run(
            [*ssh, name + "@127.0.0.1", "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded(
                "$i=[Security.Principal.WindowsIdentity]::GetCurrent(); "
                f"if($i.User.Value -cne {quote(before['sid'])} -or ([Security.Principal.WindowsPrincipal]::new($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){{throw 'wrong repaired SSH identity'}}; 'PARTIAL_KEY_ACL_RECOVERY_OK'"
            )], capture_output=True, text=True, timeout=45,
        )
        assert probe.returncode == 0 and "PARTIAL_KEY_ACL_RECOVERY_OK" in probe.stdout, probe.stderr
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        tunnel = subprocess.Popen(
            [*ssh, "-o", "ExitOnForwardFailure=yes", "-N", "-L",
             f"127.0.0.1:{port}:127.0.0.1:3389", name + "@127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 30
        while True:
            assert tunnel.poll() is None, "SSH forwarding process exited"
            try:
                connection = socket.create_connection(("127.0.0.1", port), timeout=2)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        with connection:
            connection.settimeout(10)
            # X.224 connection request plus RDP negotiation request (TLS/NLA).
            connection.sendall(bytes.fromhex("030000130ee000000000000100080003000000"))
            reply = b""
            size = 4
            while len(reply) < size:
                chunk = connection.recv(size - len(reply))
                assert chunk, "truncated RDP response"
                reply += chunk
                if len(reply) == 4:
                    size = int.from_bytes(reply[2:4], "big")
                    assert 19 <= size <= 1024, "invalid RDP response length"
        assert reply[:2] == b"\x03\x00", "no real RDP negotiation response"
        assert reply[5] == 0xD0, "RDP server did not return X.224 confirmation"
        assert reply[11] == 2, "RDP negotiation failed instead of selecting TLS/NLA"
        assert struct.unpack_from("<H", reply, 13)[0] == 8
        assert struct.unpack_from("<I", reply, 15)[0] in (1, 2)
        with capsys.disabled():
            print("COMPLETE_NATIVE_GUEST_PROVISIONING_AND_SSH_RDP_OK")
    finally:
        try:
            if tunnel:
                tunnel.terminate()
                try:
                    tunnel.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    tunnel.kill()
                    tunnel.communicate(timeout=5)
        finally:
            cleanup = powershell(
                "$password=''; $name='';\n" + AUTOLOGON_SCRIPT + rf"""
Set-ItemProperty $winlogon -Name AutoAdminLogon -Value '0'
Unregister-ScheduledTask -TaskName YokeQaMachineSettings -Confirm:$false -ErrorAction SilentlyContinue
# This dedicated job owns sshd; persistent hosts are excluded above.
$service=Get-Service sshd -ErrorAction Stop
if($service.Status -ne 'Stopped'){{$service.Stop()}}
$service.WaitForStatus([ServiceProcess.ServiceControllerStatus]::Stopped,[TimeSpan]::FromSeconds(10))
$service.Refresh()
if($service.Status -ne 'Stopped'){{throw 'owned fixture sshd did not stop'}}
Get-CimInstance Win32_Service -Filter "Name='sshd'" | Select-Object Name,State,ProcessId | ConvertTo-Json -Compress
$account=Get-LocalUser -Name '{name}' -ErrorAction SilentlyContinue
if($account){{
 try {{
  # GitHub decommissions the entire VM, including any still-loaded profile.
  Get-CimInstance Win32_UserProfile -Filter ("SID='"+$account.SID.Value+"'") | Select-Object SID,LocalPath,Loaded,refCount | ConvertTo-Json -Compress
  Write-Output 'DISPOSABLE_VM_DECOMMISSION_OWNS_RESIDUAL_PROFILE'
 }} finally {{Remove-LocalUser -Name '{name}'}}
}}
if(Get-LocalUser -Name '{name}' -ErrorAction SilentlyContinue){{throw 'owned fixture account remains'}}
if(Get-ScheduledTask -TaskName YokeQaMachineSettings -ErrorAction SilentlyContinue){{throw 'owned fixture task remains'}}
if((Get-Service sshd).Status -ne 'Stopped'){{throw 'owned fixture SSH service remains active'}}
""" + AUTOLOGON_CLEARED_SCRIPT, tmp_path, timeout=60,
            )
            with capsys.disabled():
                print(cleanup.stdout)
            assert cleanup.returncode == 0, cleanup.stderr
