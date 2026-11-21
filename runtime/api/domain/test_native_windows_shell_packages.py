"""Reset leaves the shell packages Windows restarts on its own running."""

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
TERMINAL = r"Microsoft.WindowsTerminal_1.21.10351.0_x64__8wekyb3d8bbwe\WindowsTerminal.exe"


def _package_directory(relative):
    return relative.split("\\")[0]


def test_shell_restarted_pattern_matches_only_the_named_packages():
    pattern = re.compile(processes._shell_restarted_pattern(), re.IGNORECASE)
    for relative in WIDGETS:
        assert pattern.search(_package_directory(relative)), relative
    for other in (
        TERMINAL,
        r"Microsoft.WidgetsPlatformRuntime_1.6.1.0_x64__otherpublisher\x.exe",
        r"Contoso.MicrosoftWindows.Client.WebExperience_1.0.0.0_x64__cw5n1h2txyewy\x.exe",
    ):
        assert not pattern.search(_package_directory(other)), other


@pytest.mark.parametrize("desktop", [False, True])
def test_every_reset_scan_skips_shell_restarted_packages(desktop):
    scripts = (
        processes.profile_process_stop_script(HOME, PRESERVED_DIRECTORIES, desktop=desktop),
        processes.profile_process_discovery_script(HOME, PRESERVED_DIRECTORIES),
    )
    for script in scripts:
        assert "$shellRestarted=" + quote(processes._shell_restarted_pattern()) in script
        assert script.index("$shellRestarted=") < script.index("function Get-YokeProfileProcesses")
        assert "-match $shellRestarted){continue}" in script


def _fixture(desktop, relatives):
    return rf"""$profileRoot={quote(HOME)}
$env:ProgramFiles='C:\Program Files'
$windowsAppsRoot=Join-Path $env:ProgramFiles 'WindowsApps'
$relatives=ConvertFrom-Json -InputObject {quote(json.dumps(relatives))}
""" + r"""
$entries=@()
$stops=@()
foreach($relative in @($relatives)){
 $entries+= [pscustomobject]@{Id=$entries.Count+1;Path=(Join-Path $windowsAppsRoot $relative);SessionId=1;MainWindowHandle=1;HasExited=$false}
}
function Get-Process($Id){if($Id -eq $PID){@{SessionId=1}}else{$entries}}
function Get-YokeOwnedExecutable($processId){if($processId -ne $PID){$entries[$processId-1].Path}}
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
function Stop-Process($InputObject,[switch]$Force){$script:stops+=$InputObject.Path; $InputObject.HasExited=$true}
try {
""" + processes.profile_process_stop_script(HOME, PRESERVED_DIRECTORIES, desktop=desktop) + r"""
} finally {Write-Output ('FIXTURE_STOPS '+(ConvertTo-Json -Compress -InputObject @($stops)))}
"""


def _run(tmp_path, monkeypatch, desktop, relatives):
    monkeypatch.setattr(processes, "_PROCESS_IDENTITY", "")
    script_file = tmp_path / "shell-packages.ps1"
    script_file.write_text("$ErrorActionPreference='Stop'\n" + _fixture(desktop, relatives), encoding="utf-8-sig")
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
def test_ssh_rescan_ignores_shell_packages_and_still_refuses_terminal(tmp_path, monkeypatch):
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
def test_desktop_targets_name_no_shell_package(tmp_path, monkeypatch):
    result, records = _run(tmp_path, monkeypatch, True, [*WIDGETS, TERMINAL])
    assert result.returncode == 0, result.stderr
    terminal = r"C:\Program Files\WindowsApps" + "\\" + TERMINAL
    assert records["FIXTURE_STOPS "] == [terminal]
    assert records[processes.STOPPED_MARKER] == [terminal]
    assert [app["target"] for app in records[processes.TARGETS_MARKER]] == [
        r"shell:AppsFolder\Microsoft.WindowsTerminal_8wekyb3d8bbwe!App",
    ]
