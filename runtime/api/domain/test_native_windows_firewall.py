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

from yoke_harness.native_windows import provision
from yoke_harness.native_windows import process_input
from yoke_harness.native_windows.autologon import SCRIPT as AUTOLOGON_SCRIPT
from yoke_harness.native_windows.firewall import SCRIPT as FIREWALL_SCRIPT
from yoke_harness.native_windows.transport import encoded, quote
from yoke_contracts.owner_private_path import is_owner_private_file

pytestmark = pytest.mark.windows


def powershell(script, directory, timeout=300):
    path = directory / (uuid4().hex + ".ps1")
    path.write_text("$ErrorActionPreference='Stop'\n" + script, encoding="utf-8-sig")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(path)],
        capture_output=True, text=True, timeout=timeout,
    )


@pytest.mark.parametrize("failure", [False, True])
def test_windows_input_file_is_private_exact_and_removed(monkeypatch, failure):
    seen = []
    monkeypatch.setattr(process_input, "WINDOWS_CONTROLLER", True)

    def run(argv, **kwargs):
        source = kwargs["stdin"]
        seen.append(Path(source.name))
        assert is_owner_private_file(source.name)
        assert "input" not in kwargs
        assert source.read() == b"exact framed bytes" * 1000
        if failure:
            raise subprocess.TimeoutExpired(argv, 30)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(process_input.subprocess, "run", run)
    if failure:
        with pytest.raises(subprocess.TimeoutExpired):
            process_input.run_ssh(["ssh"], input_text="exact framed bytes" * 1000)
    else:
        assert process_input.run_ssh(["ssh"], input_text="exact framed bytes" * 1000).returncode == 0
    assert seen and not seen[0].exists() and not seen[0].parent.exists()


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
    monkeypatch.setattr(provision, "machine_capability_secret_path", lambda *a: key)
    monkeypatch.setattr(provision, "read_machine_capability_secret", lambda *a: custody.get("password"))
    monkeypatch.setattr(provision, "store_machine_capability_secret", lambda *a: custody.update(password=a[-1]))
    actual_admin_script = provision.admin_script
    stages = []

    def guest(key, host, user, script, **kwargs):
        stages.append(script)
        if len(stages) == 1:
            # Equivalent to the Azure guest bootstrap, without Azure or mocks
            # of any PowerShell command. Later stages use real framed SSH.
            return powershell(script, tmp_path, timeout=900)
        try:
            return actual_admin_script(key, host, user, script, **kwargs)
        except subprocess.TimeoutExpired:
            diagnostic = powershell(
                "Get-Service sshd | Format-List Name,Status; "
                "Get-NetTCPConnection -LocalPort 22 -ErrorAction SilentlyContinue | Format-List State,LocalAddress; "
                "Get-Item 'C:\\ProgramData\\YokeQaProvision.ps1' -ErrorAction SilentlyContinue | Format-List Length,LastWriteTime; "
                "Get-WinEvent -LogName OpenSSH/Operational -MaxEvents 15 -ErrorAction SilentlyContinue | Select-Object TimeCreated,Message | Format-List",
                tmp_path,
            )
            with capsys.disabled():
                print(diagnostic.stdout)
                print(diagnostic.stderr)
            raise RuntimeError("Real SSH guest stage timed out; inspect OpenSSH diagnostics") from None

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
            assert result.returncode == 0, result.stderr
            assert "TOKEN_OK" in result.stdout
        checks = rf"""
$u=Get-LocalUser -Name '{name}'
$p=Get-ItemProperty -LiteralPath ('HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\'+$u.SID.Value)
if(!(Test-Path -LiteralPath (Join-Path $p.ProfileImagePath 'NTUSER.DAT'))){{throw 'profile hive missing'}}
$task=Get-ScheduledTask -TaskName YokeQaMachineSettings
if($task.Principal.UserId -notin @('SYSTEM','S-1-5-18')){{throw 'recovery task is not SYSTEM'}}
if(!(Test-Path 'C:\ProgramData\YokeQa\private\machine-settings.ps1')){{throw 'recovery program missing'}}
if(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name DefaultPassword -ErrorAction SilentlyContinue){{throw 'plaintext autologon password'}}
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
        # Retry the entire script through real SSH, including profile reuse.
        provision.provision("fixture", "fixture", "127.0.0.1", "fixture", admin, name,
                            bootstrap_transport="ssh")
        capsys.readouterr()
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
$account=Get-LocalUser -Name '{name}' -ErrorAction SilentlyContinue
if($account){{
 try {{Get-CimInstance Win32_UserProfile -Filter ("SID='"+$account.SID.Value+"'") | Remove-CimInstance}}
 finally {{Remove-LocalUser -Name '{name}'}}
}}
""", tmp_path,
            )
            assert cleanup.returncode == 0, cleanup.stderr
