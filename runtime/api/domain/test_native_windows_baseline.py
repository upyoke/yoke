"""Real Windows profile-copy failures retain a private diagnostic log."""

import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness.native_windows.baseline import profile_copy_script, profile_script
from yoke_harness.native_windows.transport import quote
from yoke_harness.native_windows.profile_path import HELPERS as PATH_HELPERS


pytestmark = pytest.mark.windows


@pytest.mark.windows_only(reason="requires Windows robocopy and file-sharing locks")
def test_locked_profile_copy_preserves_failure_log_and_never_seals(tmp_path):
    home = str(tmp_path / "profile")
    golden = str(tmp_path / "golden")
    copy = profile_script(SimpleNamespace(home=home), "capture", golden)
    script = (
        "$ErrorActionPreference='Stop'\n"
        f"$homeRoot={quote(home)}; $goldenRoot={quote(golden)}\n"
        r"""
New-Item -ItemType Directory -Path $homeRoot | Out-Null
$ownedFile=Join-Path $homeRoot 'locked-fixture.txt'
[IO.File]::WriteAllText($ownedFile,'fixture')
$lock=[IO.File]::Open($ownedFile,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$ownedLog=$null
try {
 try {
"""
        + copy
        + r"""
  throw 'fixture_copy_unexpectedly_succeeded'
 } catch {
  $message=$_.Exception.Message
  if($message -notmatch 'windows_profile_copy_failed: robocopy exit (\d+); (.*ERROR 32 .*locked-fixture\.txt.*); inspect private log (.+); preserve the golden'){
   throw
  }
  if([int]$Matches[1] -lt 8){throw 'failure exit code lost'}
  $ownedLog=$Matches[3]
  if(!(Test-Path -LiteralPath $ownedLog -PathType Leaf)){throw 'private log missing'}
  if(!(Get-Content -LiteralPath $ownedLog -Raw).Contains('locked-fixture.txt')){throw 'failing file diagnostic lost'}
  if(Test-Path -LiteralPath (Join-Path $goldenRoot 'sealed')){throw 'failed golden sealed'}
  if(Test-Path -LiteralPath (Join-Path $goldenRoot 'state.json')){throw 'failed copy recorded baseline state'}
  Write-Output 'PRIVATE_COPY_FAILURE_PROVED'
 }
} finally {
 $lock.Dispose()
 if($ownedLog){Remove-Item -LiteralPath $ownedLog -Force}
}
"""
    )
    script_file = tmp_path / "copy-fixture.ps1"
    script_file.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script_file)],
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr
    assert "PRIVATE_COPY_FAILURE_PROVED" in result.stdout


@pytest.mark.windows_only(reason="requires Windows robocopy and file-sharing locks")
def test_live_containers_survive_both_mirrors_while_settings_restore(tmp_path):
    home = str(tmp_path / "profile")
    golden = str(tmp_path / "golden")
    mirror = profile_copy_script(SimpleNamespace(home=home), golden)
    script = (
        "$ErrorActionPreference='Stop'\n"
        f"$homeRoot={quote(home)}; $goldenRoot={quote(golden)}\n"
        r"""
$goldenProfile=Join-Path $goldenRoot 'profile'
$live=@(
 'AppData\Local\Packages\Fixture_package\LocalState\identity.bin',
 'AppData\Local\Claude-Data\identity.bin',
 'AppData\Local\ConnectedDevicesPlatform\L.fixture\ActivitiesCache.db-shm',
 '.codex\.codex-provisioning-0123456789abcdef.guard'
)
$locks=@()
try {
 foreach($relative in $live){
  $p=Join-Path $homeRoot $relative
  New-Item -ItemType Directory -Path (Split-Path -Parent $p) -Force|Out-Null
  [IO.File]::WriteAllText($p,'LIVE_IDENTITY_FIXTURE')
  $locks+=,[IO.File]::Open($p,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
 }
 $settings=Join-Path $homeRoot '.claude\settings.json'
 New-Item -ItemType Directory -Path (Split-Path -Parent $settings) -Force|Out-Null
 [IO.File]::WriteAllText($settings,'{"skipDangerousModePermissionPrompt":true}')
 $nonGuard=Join-Path $homeRoot '.codex-provisioning-0123456789abcdef.guard'
 [IO.File]::WriteAllText($nonGuard,'BASELINE')
 [IO.File]::WriteAllText((Join-Path $homeRoot 'ordinary.txt'),'BASELINE')
 $source=$homeRoot; $target=$goldenProfile
"""
        + mirror
        + r"""
 foreach($relative in $live){
  if(Test-Path -LiteralPath (Join-Path $goldenProfile $relative)){throw 'live container captured'}
 }
 $goldenSetting=Join-Path $goldenProfile '.claude\settings.json'
 if(!(Get-Content -LiteralPath $goldenSetting -Raw|ConvertFrom-Json).skipDangerousModePermissionPrompt){throw 'setting not captured'}
 Remove-Item -LiteralPath $settings
 [IO.File]::WriteAllText((Join-Path $homeRoot 'ordinary.txt'),'CHANGED')
 [IO.File]::WriteAllText($nonGuard,'CHANGED')
 [IO.File]::WriteAllText((Join-Path $homeRoot 'extra.txt'),'EXTRA')
 $source=$goldenProfile; $target=$homeRoot
"""
        + mirror
        + r"""
 if([IO.File]::ReadAllText((Join-Path $homeRoot 'ordinary.txt')) -cne 'BASELINE'){throw 'ordinary file not restored'}
 if([IO.File]::ReadAllText($nonGuard) -cne 'BASELINE'){throw 'guard name outside .codex was excluded'}
 if(Test-Path -LiteralPath (Join-Path $homeRoot 'extra.txt')){throw 'extra file not removed'}
 if(!(Get-Content -LiteralPath $settings -Raw|ConvertFrom-Json).skipDangerousModePermissionPrompt){throw 'setting not restored'}
 foreach($lock in $locks){
  $lock.Position=0
  $bytes=New-Object byte[] $lock.Length
  if($lock.Read($bytes,0,$bytes.Length) -ne $bytes.Length -or [Text.Encoding]::UTF8.GetString($bytes) -cne 'LIVE_IDENTITY_FIXTURE'){throw 'live identity changed'}
 }
 Write-Output 'LIVE_CONTAINERS_AND_SETTINGS_PROVED'
} finally {
 foreach($lock in $locks){$lock.Dispose()}
}
"""
    )
    script_file = tmp_path / "mirror-fixture.ps1"
    script_file.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script_file)],
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr
    assert "LIVE_CONTAINERS_AND_SETTINGS_PROVED" in result.stdout


@pytest.mark.windows_only(reason="requires the Windows registry")
@pytest.mark.parametrize("kind,value", [
    ("String", r"%USERPROFILE%\fixture;C:\base"),
    ("ExpandString", r"%USERPROFILE%\fixture;C:\base"),
    ("String", ""), ("ExpandString", ""), (None, None),
])
def test_user_path_roundtrip_retains_raw_kind_empty_and_absent(tmp_path, kind, value):
    initial = (
        f"$key.SetValue('PATH',{quote(value)},[Microsoft.Win32.RegistryValueKind]::{kind})"
        if kind else ""
    )
    expected = (
        f"if(!$before.exists -or $before.raw -cne {quote(value)} -or $before.kind -cne '{kind}'){{throw 'snapshot changed raw PATH'}}"
        if kind else "if($before.exists -or $null -ne $before.raw -or $null -ne $before.kind){throw 'absent PATH lost'}"
    )
    script = "$ErrorActionPreference='Stop'\n" + PATH_HELPERS + r"""
$owned='Software\YokeQaFixture-'+[Guid]::NewGuid().ToString('N')
$key=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($owned)
try {
""" + initial + r"""
 $before=Read-YokeUserPath $key
""" + expected + r"""
 $key.SetValue('Path','MUTATED',[Microsoft.Win32.RegistryValueKind]::String)
 Restore-YokeUserPath $key $before
 $after=Read-YokeUserPath $key
 if($after.exists -ne $before.exists -or $after.raw -cne $before.raw -or $after.kind -cne $before.kind){throw 'raw PATH roundtrip lost'}
 Write-Output 'RAW_PATH_ROUNDTRIP_PROVED'
} finally {
 $key.Dispose()
 [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($owned)
}
"""
    script_file = tmp_path / "path-fixture.ps1"
    script_file.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script_file)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "RAW_PATH_ROUNDTRIP_PROVED" in result.stdout


@pytest.mark.windows_only(reason="requires Windows profile reset")
def test_legacy_path_snapshot_refuses_before_profile_mirror(tmp_path):
    home, golden = str(tmp_path / "profile"), str(tmp_path / "golden")
    reset = profile_script(SimpleNamespace(home=home), "reset", golden)
    script = (
        "$ErrorActionPreference='Stop'\n"
        f"$homeRoot={quote(home)}; $goldenRoot={quote(golden)}\n"
        r"""
New-Item -ItemType Directory -Path $homeRoot,$goldenRoot|Out-Null
$sentinel=Join-Path $homeRoot 'untouched.txt'
[IO.File]::WriteAllText($sentinel,'UNCHANGED')
[IO.File]::WriteAllText((Join-Path $goldenRoot 'sealed'),'fixture')
[IO.File]::WriteAllText((Join-Path $goldenRoot 'state.json'),'{"user_path":"legacy","tasks":[]}')
try {
""" + reset + r"""
 throw 'legacy reset unexpectedly accepted'
} catch {
 if($_.Exception.Message -notmatch 'windows_path_snapshot_invalid'){throw}
 if([IO.File]::ReadAllText($sentinel) -cne 'UNCHANGED'){throw 'profile mutated before refusal'}
 Write-Output 'LEGACY_REFUSED_BEFORE_MIRROR'
}
"""
    )
    script_file = tmp_path / "legacy-fixture.ps1"
    script_file.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script_file)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "LEGACY_REFUSED_BEFORE_MIRROR" in result.stdout
