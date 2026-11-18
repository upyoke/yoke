"""Exercise SYSTEM proof error boundaries and the real tray startup policy."""

import json
import subprocess
from uuid import uuid4

import pytest

from yoke_harness.native_windows.admin import admin_script
from yoke_harness.native_windows.powershell import quote
from yoke_harness.native_windows.tailnet import SCRIPT
from yoke_harness.native_windows.tailnet_startup import SCRIPT as STARTUP_SCRIPT

pytestmark = pytest.mark.windows
KNOWN = "windows_rdp_firewall_failed: require a running Tailscale self identity"
UNKNOWN = "windows_rdp_firewall_failed: SYSTEM tailnet probe failed (unclassified)"


@pytest.mark.windows_only(reason="requires native Windows PowerShell")
@pytest.mark.parametrize("reason,expected", [
    (KNOWN, KNOWN),
    ("native parser secret-sentinel", UNKNOWN),
    ("windows_rdp_firewall_failed: secret-sentinel", UNKNOWN),
])
def test_generated_probe_payload_retains_only_allowlisted_errors(tmp_path, reason, expected):
    result_path = tmp_path / "result.json"
    body = "param($Executable); throw " + quote(reason)
    script = SCRIPT + "\n" + (
        "$payload=New-YokeTailnetProbePayload 'unused' " + quote(body)
        + " 'test-nonce' " + quote(str(result_path)) + "\n"
        "& ([ScriptBlock]::Create($payload))\n"
        "$r=[IO.File]::ReadAllText(" + quote(str(result_path)) + ")|ConvertFrom-Json\n"
        "@{nonce=$r.nonce;ok=$r.ok;error=(Get-YokeTailnetFailure $r.error)}|ConvertTo-Json -Compress"
    )
    path = tmp_path / "payload.ps1"
    path.write_text("$ErrorActionPreference='Stop'\n" + script, encoding="utf-8-sig")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"nonce": "test-nonce", "ok": False, "error": expected}
    assert "secret-sentinel" not in result.stdout + result.stderr + result_path.read_text()


def verify_real_system_tailnet_errors(key, admin):
    """Called after full provisioning, with real SYSTEM tasks and private ACLs."""
    for reason, expected in [(KNOWN, KNOWN), ("windows_secret: secret-sentinel", UNKNOWN)]:
        body = "param($Executable); throw " + quote(reason)
        script = SCRIPT + "\n$body=" + quote(body) + r"""
try {Invoke-YokeSystemTailnetProof (Join-Path $PSHOME 'powershell.exe') $body;throw 'Expected probe failure'}
catch {Write-Output ('FILTERED_REASON:'+$_.Exception.Message);exit 42}
"""
        result = admin_script(key, "127.0.0.1", admin, script)
        assert result.returncode == 42, result.stderr
        assert result.stdout.strip() == "FILTERED_REASON:" + expected
        assert "secret-sentinel" not in result.stdout + result.stderr
        assert result.staging_diagnostics["cleanup"] == "verified_absent"


def verify_real_tailnet_startup_policy(powershell, tmp_path):
    """Use real shortcuts, signatures, owners and backup ACLs on the native runner."""
    root = tmp_path / ("tray-" + uuid4().hex)
    script = STARTUP_SCRIPT + "\n$root=" + quote(str(root)) + r"""
$startup=Join-Path $root 'Startup';$private=Join-Path $root 'private';$exe=Join-Path $root 'tray.exe'
New-Item -ItemType Directory -Path $startup,$private -ErrorAction Stop|Out-Null
Copy-Item -LiteralPath (Join-Path $PSHOME 'powershell.exe') -Destination $exe -ErrorAction Stop
foreach($p in @($root,$startup,$private,$exe)){
 $acl=Get-Acl -LiteralPath $p;$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
 if($p -eq $private){
  $acl.SetAccessRuleProtection($true,$false)
  foreach($rule in @($acl.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier]))){$acl.RemoveAccessRuleSpecific($rule)}
  foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))}
 }
 Set-Acl -LiteralPath $p -AclObject $acl -ErrorAction Stop
}
$shell=New-Object -ComObject WScript.Shell
$renamed=Join-Path $startup 'Renamed.lnk'
$link=$shell.CreateShortcut($renamed);$link.TargetPath='C:\Program Files\Tailscale\tailscale-ipn.exe';$link.Save()
$renamedHash=(Get-FileHash -LiteralPath $renamed -Algorithm SHA256).Hash
try {Disable-YokeTailnetTrayStartup -StartupRoot $startup -PrivateRoot $private -Executable $exe;throw 'Accepted renamed tray startup'}
catch {if($_.Exception.Message -notlike 'windows_tailnet_startup_unexpected:*'){throw}}
if((Get-FileHash -LiteralPath $renamed -Algorithm SHA256).Hash -cne $renamedHash){throw 'Changed refused renamed link'}
Remove-Item -LiteralPath $renamed -ErrorAction Stop
function Set-FixtureShortcutOwner($path,$stage) {
 $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
 $acl=Get-Acl -LiteralPath $path
 $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
 Set-Acl -LiteralPath $path -AclObject $acl -ErrorAction Stop
 $owner=(Get-Acl -LiteralPath $path).GetOwner([Security.Principal.SecurityIdentifier]).Value
 if($owner -cne 'S-1-5-32-544' -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $hash){throw ('Fixture ownership/bytes invalid after '+$stage)}
 Write-Output ('FIXTURE_OWNER_STAGE:'+$stage+':'+$owner)
}
$path=Join-Path $startup 'Tailscale.lnk';$shell=New-Object -ComObject WScript.Shell
$link=$shell.CreateShortcut($path);$link.TargetPath=$exe;$link.Arguments='-Unexpected';$link.Save()
Set-FixtureShortcutOwner $path 'unexpected-argument-save'
$before=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
try {Disable-YokeTailnetTrayStartup -StartupRoot $startup -PrivateRoot $private -Executable $exe;throw 'Accepted unexpected arguments'}
catch {if($_.Exception.Message -notlike 'windows_tailnet_startup_target_invalid:*'){throw}}
if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $before){throw 'Changed refused shortcut'}
$link=$shell.CreateShortcut($path);$link.Arguments='';$link.Save()
Set-FixtureShortcutOwner $path 'expected-shortcut-save'
$before=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
$result=Disable-YokeTailnetTrayStartup -StartupRoot $startup -PrivateRoot $private -Executable $exe
if($result.trayStartup -cne 'disabled' -or (Test-Path -LiteralPath $path) -or (Get-FileHash -LiteralPath $result.backup -Algorithm SHA256).Hash -cne $before){throw 'Shortcut was not privately backed up and disabled'}
Assert-YokeTailnetStartupPrivate $result.backup $false
$again=Disable-YokeTailnetTrayStartup -StartupRoot $startup -PrivateRoot $private -Executable $exe
if($again.trayStartup -cne 'absent'){throw 'Not idempotent'}
if(Test-Path -LiteralPath $path){throw 'Fixture restore destination unexpectedly exists'}
Copy-Item -LiteralPath $result.backup -Destination $path -ErrorAction Stop
Set-FixtureShortcutOwner $path 'collision-restore-copy'
[IO.File]::AppendAllText($result.backup,'collision')
$collision=(Get-FileHash -LiteralPath $result.backup -Algorithm SHA256).Hash
try {Disable-YokeTailnetTrayStartup -StartupRoot $startup -PrivateRoot $private -Executable $exe;throw 'Accepted changed backup'}
catch {if($_.Exception.Message -notlike 'windows_tailnet_startup_backup_invalid:*'){throw}}
if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $before -or (Get-FileHash -LiteralPath $result.backup -Algorithm SHA256).Hash -cne $collision){throw 'Changed collision evidence'}
'TRAY_STARTUP_POLICY_OK'
"""
    result = powershell(script, tmp_path, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "TRAY_STARTUP_POLICY_OK" in result.stdout
