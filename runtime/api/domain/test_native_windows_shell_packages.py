"""Reset leaves packages that Windows launches on its own running."""

import json
import re
import subprocess

import pytest

from yoke_harness.native_windows import profile_processes as processes
from yoke_harness.native_windows.baseline import PRESERVED_DIRECTORIES
from yoke_harness.native_windows.transport import quote

pytestmark = pytest.mark.windows

HOME = r"C:\Users\yokeqa"
WIDGETS = (
    r"MicrosoftWindows.Client.WebExperience_524.33200.0.0_x64__cw5n1h2txyewy\Dashboard\Widgets.exe",
    r"Microsoft.WidgetsPlatformRuntime_1.6.1.0_x64__8wekyb3d8bbwe\WidgetService\WidgetService.exe",
    r"Microsoft.StartExperiencesApp_1.36.1.0_x64__8wekyb3d8bbwe\MicrosoftStartFeedProvider.exe",
)
STORE_EXTENSION = r"Microsoft.WindowsStore_22610.1401.10.0_x64__8wekyb3d8bbwe\StoreDesktopExtension.exe"
STORE_UI = r"Microsoft.WindowsStore_22610.1401.10.0_x64__8wekyb3d8bbwe\WinStore.App.exe"
TERMINAL = r"Microsoft.WindowsTerminal_1.21.10351.0_x64__8wekyb3d8bbwe\WindowsTerminal.exe"
POSTGRES = HOME + r"\.yoke\postgres\17.11.1\bin\postgres.exe"


def _package_directory(relative):
    return relative.split("\\")[0]


def test_windows_launched_pattern_matches_only_the_named_packages():
    pattern = re.compile(processes._windows_launched_pattern(), re.IGNORECASE)
    for relative in (*WIDGETS, STORE_EXTENSION, STORE_UI):
        assert pattern.search(_package_directory(relative)), relative
    for other in (
        TERMINAL,
        r"Microsoft.WindowsStore_22610.1401.10.0_x64__otherpublisher\StoreDesktopExtension.exe",
        r"Contoso.Microsoft.WindowsStore_22610.1401.10.0_x64__8wekyb3d8bbwe\WinStore.App.exe",
        r"OpenAI.Codex_1.0.0.0_x64__2p2nqsd0c76g0\Codex.exe",
        r"Microsoft.WidgetsPlatformRuntime_1.6.1.0_x64__otherpublisher\x.exe",
        r"Contoso.MicrosoftWindows.Client.WebExperience_1.0.0.0_x64__cw5n1h2txyewy\x.exe",
    ):
        assert not pattern.search(_package_directory(other)), other


@pytest.mark.parametrize("desktop", [False, True])
def test_every_reset_scan_skips_windows_launched_packages(desktop):
    scripts = (
        processes.profile_process_stop_script(HOME, PRESERVED_DIRECTORIES, desktop=desktop),
        processes.profile_process_discovery_script(HOME, PRESERVED_DIRECTORIES),
    )
    for script in scripts:
        assert "$windowsLaunched=" + quote(processes._windows_launched_pattern()) in script
        assert script.index("$windowsLaunched=") < script.index("function Get-YokeProfileProcesses")
        assert "-match $windowsLaunched){continue}" in script


def _fixture(desktop, relatives, restarts, process_session):
    # restarts=None keeps exited entries listed, so the SSH rescan sees a survivor.
    # Otherwise exited entries leave the listing and each of the next `restarts`
    # stops starts a replacement; -1 restarts on every stop.
    return rf"""$profileRoot={quote(HOME)}
$env:ProgramFiles='C:\Program Files'
$windowsAppsRoot=Join-Path $env:ProgramFiles 'WindowsApps'
$relatives=ConvertFrom-Json -InputObject {quote(json.dumps(relatives))}
$hideExited=${'true' if restarts is not None else 'false'}
$restarts={restarts or 0}
$processSession={process_session}
""" + r"""
$entries=@()
$stops=@()
foreach($relative in @($relatives)){
 $path=if($relative -like 'C:\*'){$relative}else{Join-Path $windowsAppsRoot $relative}
 $entries+= [pscustomobject]@{Id=$entries.Count+1;Path=$path;SessionId=$processSession;MainWindowHandle=1;HasExited=$false}
}
function Get-Process($Id){if($Id -eq $PID){@{SessionId=1}}else{$script:entries | Where-Object {!$hideExited -or !$_.HasExited}}}
function Get-YokeOwnedExecutable($processId){if($processId -ne $PID){$script:entries[$processId-1].Path}}
function Get-AppxPackage {
 foreach($relative in @($relatives)){
  $directory=$relative.Split('\')[0]
  @{InstallLocation=(Join-Path $windowsAppsRoot $directory);PackageFamilyName=($directory -replace '_.*__','_')}
 }
}
function Get-AppxPackageManifest($Package) {
 $exe=@($relatives | Where-Object {(Join-Path $windowsAppsRoot $_).StartsWith($Package.InstallLocation+'\')})[0]
 [xml]('<Package><Applications><Application Id="App" Executable="'+$exe.Substring($exe.IndexOf('\')+1)+'"/></Applications></Package>')
}
function Stop-Process($InputObject,[switch]$Force){
 $script:stops+=$InputObject.Path; $InputObject.HasExited=$true
 if($script:restarts){
  $script:restarts--
  $script:entries+= [pscustomobject]@{Id=$script:entries.Count+1;Path=$InputObject.Path;SessionId=1;MainWindowHandle=0;HasExited=$false}
 }
}
try {
""" + processes.profile_process_stop_script(HOME, PRESERVED_DIRECTORIES, desktop=desktop) + r"""
} finally {Write-Output ('FIXTURE_STOPS '+(ConvertTo-Json -Compress -InputObject @($stops)))}
"""


def _run(tmp_path, monkeypatch, desktop, relatives, restarts=None, *, process_session=1):
    monkeypatch.setattr(processes, "_PROCESS_IDENTITY", "")
    script_file = tmp_path / "shell-packages.ps1"
    script_file.write_text(
        "$ErrorActionPreference='Stop'\n" + _fixture(desktop, relatives, restarts, process_session),
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script_file)],
        capture_output=True, text=True, timeout=60,
    )
    records = {
        marker: json.loads(line[len(marker):])
        for line in result.stdout.splitlines()
        for marker in ("FIXTURE_STOPS ", processes.STOPPED_MARKER, processes.TARGETS_MARKER)
        if line.startswith(marker)
    }
    return result, records


@pytest.mark.windows_only(reason="requires Windows PowerShell")
def test_ssh_rescan_ignores_widgets_and_still_refuses_terminal(tmp_path, monkeypatch):
    widgets_only, records = _run(tmp_path, monkeypatch, False, list(WIDGETS))
    assert widgets_only.returncode == 0, widgets_only.stderr
    assert records["FIXTURE_STOPS "] == [] and records[processes.STOPPED_MARKER] == []

    refused, records = _run(tmp_path, monkeypatch, False, [*WIDGETS, TERMINAL])
    assert refused.returncode != 0
    assert "windows_reset_profile_process_running" in refused.stderr
    assert "WindowsTerminal.exe" in refused.stderr
    assert not any(name in refused.stderr for name in ("Widgets.exe", "WidgetService", "StartFeed"))
    assert [path.split("\\")[-1] for path in records["FIXTURE_STOPS "]] == ["WindowsTerminal.exe"]


@pytest.mark.windows_only(reason="requires Windows PowerShell")
def test_ssh_rescan_ignores_store_extension_in_the_console_session(tmp_path, monkeypatch):
    result, records = _run(tmp_path, monkeypatch, False, [STORE_EXTENSION], process_session=2)
    assert result.returncode == 0, result.stderr
    assert records["FIXTURE_STOPS "] == []
    assert records[processes.STOPPED_MARKER] == []

    refused, records = _run(
        tmp_path, monkeypatch, False, [STORE_EXTENSION, TERMINAL], process_session=2,
    )
    assert refused.returncode != 0
    assert "windows_reset_profile_process_running" in refused.stderr
    reason = "test-user processes are still running from the resettable profile or WindowsApps:"
    assert reason in " ".join(refused.stderr.split())
    assert "WindowsTerminal.exe" in refused.stderr
    assert "StoreDesktopExtension" not in refused.stderr
    assert records["FIXTURE_STOPS "] == []


@pytest.mark.windows_only(reason="requires Windows PowerShell")
def test_desktop_targets_name_only_terminal_among_windows_launched_packages(tmp_path, monkeypatch):
    result, records = _run(
        tmp_path, monkeypatch, True, [*WIDGETS, STORE_EXTENSION, STORE_UI, TERMINAL],
    )
    assert result.returncode == 0, result.stderr
    terminal = r"C:\Program Files\WindowsApps" + "\\" + TERMINAL
    assert records["FIXTURE_STOPS "] == [terminal]
    assert records[processes.STOPPED_MARKER] == [terminal]
    assert [app["target"] for app in records[processes.TARGETS_MARKER]] == [
        r"shell:AppsFolder\Microsoft.WindowsTerminal_8wekyb3d8bbwe!App",
    ]


@pytest.mark.windows_only(reason="requires Windows PowerShell")
@pytest.mark.parametrize("desktop", [False, True])
def test_stop_pass_also_stops_a_process_started_during_it(tmp_path, monkeypatch, desktop):
    result, records = _run(tmp_path, monkeypatch, desktop, [POSTGRES], restarts=1)
    assert result.returncode == 0, result.stderr
    assert records["FIXTURE_STOPS "] == [POSTGRES, POSTGRES]
    assert records[processes.STOPPED_MARKER] == [POSTGRES, POSTGRES]


@pytest.mark.windows_only(reason="requires Windows PowerShell")
@pytest.mark.parametrize("desktop", [False, True])
def test_stop_pass_refuses_at_deadline_naming_the_latest_restart(tmp_path, monkeypatch, desktop):
    assert "AddSeconds(20)" in processes._STOP
    monkeypatch.setattr(processes, "_STOP", processes._STOP.replace("AddSeconds(20)", "AddSeconds(2)"))
    result, records = _run(tmp_path, monkeypatch, desktop, [POSTGRES], restarts=-1)
    assert result.returncode != 0
    assert "windows_reset_profile_process_running" in result.stderr
    latest = len(records["FIXTURE_STOPS "]) + 1
    # PowerShell wraps long error lines, so compare without whitespace.
    assert f"WindowsApps:{latest}{POSTGRES}" in "".join(result.stderr.split())
