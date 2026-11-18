"""Native profile provisioning, failure boundaries and password-preserving retries."""

import subprocess
from unittest.mock import Mock

import pytest

from runtime.api.domain.native_windows_fixture_cleanup import PROFILE_CLEANUP_SCRIPT
from yoke_harness.native_windows import provision
from yoke_harness.native_windows.profile import HELPERS, SCRIPT
from yoke_harness.native_windows.transport import encoded


pytestmark = pytest.mark.windows


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, "")


def test_missing_secret_cannot_reset_existing_account(monkeypatch):
    store = Mock()
    monkeypatch.setattr(provision, "machine_capability_secret_path", lambda *a: "key")
    monkeypatch.setattr(provision, "read_machine_capability_secret", lambda *a: None)
    monkeypatch.setattr(provision, "store_machine_capability_secret", store)
    monkeypatch.setattr(
        provision.subprocess, "run", lambda *a, **kw: completed("PUBLIC")
    )
    replies = iter(
        [
            completed("Native OpenSSH ready; password authentication disabled."),
            completed(returncode=1),
        ]
    )
    monkeypatch.setattr(provision, "admin_script", lambda *a, **kw: next(replies))
    with pytest.raises(RuntimeError, match="windows_existing_user_secret_required"):
        provision.provision(
            "project", "vm", "host", "group", "admin", "qa", bootstrap_transport="ssh"
        )
    store.assert_not_called()


def test_profile_failure_stops_before_journal_install_and_redacts_secret(monkeypatch):
    calls = []
    monkeypatch.setattr(provision, "machine_capability_secret_path", lambda *a: "key")
    monkeypatch.setattr(
        provision, "read_machine_capability_secret", lambda *a: "private password"
    )
    monkeypatch.setattr(
        provision.subprocess, "run", lambda *a, **kw: completed("PUBLIC")
    )

    def admin(key, host, user, script, **kwargs):
        calls.append(script)
        if len(calls) == 1:
            return completed("Native OpenSSH ready; password authentication disabled.")
        return subprocess.CompletedProcess(
            [],
            1,
            "",
            "private password windows_profile_creation_failed HRESULT 0x80070005",
        )

    monkeypatch.setattr(provision, "admin_script", admin)
    with pytest.raises(RuntimeError, match="0x80070005") as error:
        provision.provision(
            "project", "vm", "host", "group", "admin", "qa", bootstrap_transport="ssh"
        )
    assert "private password" not in str(error.value)
    assert len(calls) == 2


def powershell(script, *, timeout=45):
    try:
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
             encoded("$ErrorActionPreference='Stop';\n" + script)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or b""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        raise RuntimeError(f"native_profile_fixture_timeout after {timeout}s; stages: " + output[-1600:]) from None


@pytest.mark.windows_only(reason='requires Windows PowerShell')
@pytest.mark.parametrize("hresult", [0, -2147024713])
def test_profile_success_and_race_use_registered_actual_path(hresult):
    result = powershell(
        HELPERS
        + rf"""
$script:reads=0
function Resolve-YokeProfile($sid){{
 $script:reads++
 if($script:reads -eq 1){{return $null}}
 return 'C:\Users\qa.machine'
}}
function Invoke-YokeCreateProfile($sid,$name){{return [PSCustomObject]@{{HResult={hresult};Path='C:\Users\qa.machine'}}}}
$path=Initialize-YokeProfile 'S-1-5-21-123' 'qa'
if($path -cne 'C:\Users\qa.machine'){{throw 'actual registered path lost'}}
Write-Output 'PROFILE_OK'
"""
    )
    assert result.returncode == 0, result.stderr
    assert "PROFILE_OK" in result.stdout


@pytest.mark.windows_only(reason='requires Windows PowerShell')
@pytest.mark.parametrize("mode", ["hresult", "missing", "mismatch"])
def test_profile_failures_never_emit_success(mode):
    result = powershell(
        HELPERS
        + rf"""
$script:reads=0
function Resolve-YokeProfile($sid){{
 $script:reads++
 if($script:reads -eq 1 -or '{mode}' -eq 'missing'){{return $null}}
 return 'C:\Users\qa.machine'
}}
function Invoke-YokeCreateProfile($sid,$name){{return [PSCustomObject]@{{HResult=$(if('{mode}' -eq 'hresult'){{-2147024891}}else{{0}});Path='C:\Users\unexpected'}}}}
$path=Initialize-YokeProfile 'S-1-5-21-123' 'qa'
Write-Output 'PROFILE_OK'
"""
    )
    assert result.returncode != 0
    assert "PROFILE_OK" not in result.stdout
    if mode == "hresult":
        assert "0x80070005" in result.stderr


@pytest.mark.windows_only(reason='requires Windows account/profile APIs')
def test_real_profile_creation_and_retry_preserve_password():
    # The disposable runner bounds timeout fallout. Normal/failure exits attempt
    # profile and account cleanup independently, retaining any cleanup error.
    result = powershell(
        PROFILE_CLEANUP_SCRIPT + r"""
$name='yq'+[Guid]::NewGuid().ToString('N').Substring(0,14)
$password=[Guid]::NewGuid().ToString('N')+'aA1!'
$secure=ConvertTo-SecureString $password -AsPlainText -Force
$ownedSid=$null
try {
"""
        + SCRIPT
        + r"""
 $ownedSid=$account.SID.Value
 if(!(Test-Path -LiteralPath (Join-Path $homePath 'NTUSER.DAT'))){throw 'profile hive missing'}
 Write-Output 'NATIVE_PROFILE_CREATED'
 $first=$homePath
 Write-Output 'NATIVE_PROFILE_RETRY_BEGIN'
 $created=Invoke-YokeCreateProfile $ownedSid $name
 if($created.HResult -ne -2147024713){throw 'existing-profile result not surfaced'}
 Add-Type -AssemblyName System.DirectoryServices.AccountManagement
 $context=New-Object DirectoryServices.AccountManagement.PrincipalContext([DirectoryServices.AccountManagement.ContextType]::Machine)
 try {
  if(!$context.ValidateCredentials($name,$password)){throw 'initial password invalid'}
  $other=[Guid]::NewGuid().ToString('N')+'aA1!'
  $secure=ConvertTo-SecureString $other -AsPlainText -Force
"""
        + SCRIPT
        + r"""
  if($homePath -cne $first){throw 'profile changed on retry'}
  if(!$context.ValidateCredentials($name,$password) -or $context.ValidateCredentials($name,$other)){throw 'retry changed password'}
 } finally {$context.Dispose()}
 Write-Output 'NATIVE_PROFILE_AND_PASSWORD_OK'
} finally {
 if(!$ownedSid){$owned=Get-LocalUser -Name $name -ErrorAction SilentlyContinue; if($owned){$ownedSid=$owned.SID.Value}}
 if($ownedSid){
  try {Remove-YokeFixtureProfile $ownedSid}
  finally {Remove-LocalUser -Name $name}
 }
}
""",
        timeout=80,  # existing45s functional budget plus30s cleanup and startup
    )
    assert result.returncode == 0, result.stderr
    assert "NATIVE_PROFILE_AND_PASSWORD_OK" in result.stdout
