"""Real Windows profile-copy failures retain a private diagnostic log."""

import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness.native_windows.baseline import profile_script
from yoke_harness.native_windows.transport import quote


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
  if($message -notmatch 'windows_profile_copy_failed: robocopy exit (\d+); inspect private log (.+); preserve the unsealed golden'){
   throw
  }
  if([int]$Matches[1] -lt 8){throw 'failure exit code lost'}
  $ownedLog=$Matches[2]
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
