"""Read real console buffers while the reader's standard output is redirected."""

import subprocess

import pytest

from yoke_harness.native_windows.terminal import SCREEN_READER
from yoke_harness.native_windows.console_focus import HELPERS as FOCUS_HELPERS
from yoke_harness.native_windows.transport import quote


pytestmark = pytest.mark.windows

CONSOLELESS_PRODUCER = r"""
using System;
using System.IO;
using System.Threading;
using System.Runtime.InteropServices;
public static class ConsolelessProducer {
 [DllImport("kernel32.dll")] static extern IntPtr GetConsoleWindow();
 [STAThread] public static void Main(string[] args) {
  File.WriteAllText(args[0],GetConsoleWindow().ToInt64().ToString());
  Thread.Sleep(30000);
 }
}
"""


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
    executable = tmp_path / "consoleless-producer.exe"
    start = (
        "$child=Start-Process powershell.exe -ArgumentList " + quote(arguments) + " -WindowStyle Hidden -PassThru"
        if has_console else
        "Add-Type -TypeDefinition " + quote(CONSOLELESS_PRODUCER)
        + " -OutputType WindowsApplication -OutputAssembly " + quote(str(executable)) + ";"
        "$info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=" + quote(str(executable)) + ";"
        "$info.Arguments=" + quote('"' + str(ready) + '"') + ";$info.UseShellExecute=$false;"
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
    precondition = (
        "if([IO.File]::ReadAllText(" + quote(str(ready)) + ") -cne '0'){throw 'fixture target has a console'};"
        "$child.Refresh();if($child.HasExited){throw 'fixture target already exited'}\n"
        if not has_console else ""
    )
    script = (
        "$ErrorActionPreference='Stop'\nAdd-Type -TypeDefinition " + quote(SCREEN_READER)
        + "\n" + start + "\ntry {\n"
        + "$deadline=[datetime]::UtcNow.AddSeconds(15);while(!(Test-Path -LiteralPath "
        + quote(str(ready)) + ")){if([datetime]::UtcNow -ge $deadline){throw 'producer not ready'};Start-Sleep -Milliseconds 100}\n"
        + precondition + check
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


@pytest.mark.windows_only(reason="requires Windows window and process-token APIs")
@pytest.mark.parametrize("mode", ["owned", "missing", "ambiguous", "wrong_window"])
def test_console_focus_resolves_only_one_owned_window_and_refuses_mismatches(tmp_path, mode):
    script = (
        "$ErrorActionPreference='Stop';Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -TypeDefinition " + quote(FOCUS_HELPERS) + "\n$mode=" + quote(mode)
        + r"""
$token='YokeQa-'+[Guid]::NewGuid().ToString('N');$forms=@()
try {
 $count=if($mode -eq 'missing'){0}elseif($mode -eq 'ambiguous'){2}else{1}
 for($i=0;$i -lt $count;$i++){
  $form=New-Object Windows.Forms.Form;$form.Text=$token;$form.Show();$forms+=,$form
 }
 [Windows.Forms.Application]::DoEvents()
 if($mode -eq 'owned'){
  if([QaConsoleFocus]::Find([uint32]$PID,$token) -ne $forms[0].Handle){throw 'wrong owned window'}
 } else {
  try {
   if($mode -eq 'wrong_window'){[QaConsoleFocus]::VerifyForeground([uint32]$PID,$token,[IntPtr]::Zero,$token)}
   else{[void][QaConsoleFocus]::Find([uint32]$PID,$token)}
   throw 'mismatched window unexpectedly accepted'
  } catch {
   if($_.Exception.Message -notmatch 'windows_terminal_focus_refused'){throw}
  }
 }
 Write-Output 'OWNED_WINDOW_GUARDS_PROVED'
} finally {
 foreach($form in $forms){$form.Close();$form.Dispose()}
 [Windows.Forms.Application]::DoEvents()
}
"""
    )
    source = tmp_path / "focus-fixture.ps1"
    source.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(source)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "OWNED_WINDOW_GUARDS_PROVED" in result.stdout
