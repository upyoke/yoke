"""Read real console buffers while the reader's standard output is redirected."""

import subprocess

import pytest

from yoke_harness.native_windows.terminal import SCREEN_READER
from yoke_harness.native_windows.transport import quote


pytestmark = pytest.mark.windows


@pytest.mark.windows_only(reason="requires Windows console APIs")
@pytest.mark.parametrize("has_console", [True, False])
def test_redirected_reader_uses_real_buffer_or_retains_native_failure(tmp_path, has_console):
    producer = tmp_path / "producer.ps1"
    ready = tmp_path / "producer-ready"
    producer.write_text(
        "Write-Host 'YOKE_ACTUAL_CONSOLE_BUFFER'; [IO.File]::WriteAllText("
        + quote(str(ready)) + ",'ready'); Start-Sleep -Seconds 30",
        encoding="utf-8-sig",
    )
    arguments = '-NoLogo -NoProfile -NonInteractive -File "' + str(producer) + '"'
    start = (
        "$child=Start-Process powershell.exe -ArgumentList " + quote(arguments) + " -WindowStyle Hidden -PassThru"
        if has_console else
        "$info=[Diagnostics.ProcessStartInfo]::new();$info.FileName='powershell.exe';"
        "$info.Arguments=" + quote(arguments) + ";$info.UseShellExecute=$false;"
        "$info.CreateNoWindow=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true;"
        "$child=[Diagnostics.Process]::Start($info)"
    )
    check = r"""
 $deadline=[datetime]::UtcNow.AddSeconds(15)
 do {
  $observed=[QaConsole]::Read([uint32]$child.Id)
  if($observed.Contains('YOKE_ACTUAL_CONSOLE_BUFFER')){break}
  Start-Sleep -Milliseconds 100
 } while([datetime]::UtcNow -lt $deadline)
 if(!$observed.Contains('YOKE_ACTUAL_CONSOLE_BUFFER')){throw 'actual console text not read'}
 Write-Output 'REAL_BUFFER_AND_REDIRECTED_STDOUT_PROVED'
""" if has_console else r"""
 try {
  [QaConsole]::Read([uint32]$child.Id)
  throw 'console-less process unexpectedly attached'
 } catch {
  if($_.Exception.Message -notmatch 'windows_console_attach_failed: win32=6; reader_session=\d+; target_session=\d+'){throw}
  Write-Output 'NATIVE_FAILURE_CONTEXT_PROVED'
 }
"""
    script = (
        "$ErrorActionPreference='Stop'\nAdd-Type -TypeDefinition " + quote(SCREEN_READER)
        + "\n" + start + "\ntry {\n"
        + "$deadline=[datetime]::UtcNow.AddSeconds(15);while(!(Test-Path -LiteralPath "
        + quote(str(ready)) + ")){if([datetime]::UtcNow -ge $deadline){throw 'producer not ready'};Start-Sleep -Milliseconds 100}\n"
        + check
        + "\n} finally {if(!$child.HasExited){Stop-Process -Id $child.Id -Force};$child.Dispose()}"
    )
    reader = tmp_path / "reader.ps1"
    reader.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(reader)],
        capture_output=True, text=True, timeout=40,
    )
    assert result.returncode == 0, result.stderr
    expected = "REAL_BUFFER_AND_REDIRECTED_STDOUT_PROVED" if has_console else "NATIVE_FAILURE_CONTEXT_PROVED"
    assert expected in result.stdout
