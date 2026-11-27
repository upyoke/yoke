"""Reset removes links the golden lacks and proves no uv-managed Python is left."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness.native_windows import baseline
from yoke_harness.native_windows.baseline import (
    PRESERVED_DIRECTORIES, profile_copy_script, profile_script,
)
from yoke_harness.native_windows.profile_links import (
    link_sweep_record, stale_link_sweep_script,
)
from yoke_harness.native_windows.transport import quote

pytestmark = pytest.mark.windows

HOME = r"C:\Users\yokeqa"
GOLDEN = r"D:\goldens\fixture"
PRISTINE = json.dumps({"stage_folders": [], "uv_python_registry": False})


def test_cursor_login_is_kept_through_its_roaming_folder():
    copy = profile_copy_script(SimpleNamespace(home=HOME), GOLDEN)
    assert quote(HOME + r"\AppData\Roaming\Cursor") in copy
    assert r".config\cursor" not in copy


def test_reset_sweeps_links_after_the_mirror_and_capture_does_not():
    control = SimpleNamespace(home=HOME)
    reset = profile_script(control, "reset", GOLDEN)
    mirror = reset.index("robocopy.exe")
    sweep = reset.index("$sweepPreserved=")
    assert mirror < sweep < reset.index("Restore-YokeUserPath $pathKey")
    assert "windows_reset_uv_state_left" in reset
    assert r"Join-Path $target 'AppData\Roaming\uv\python'" in reset
    assert "$sweepPreserved" not in profile_script(control, "capture", GOLDEN)


def test_sweep_skips_live_identity_directories():
    script = stale_link_sweep_script(HOME, PRESERVED_DIRECTORIES)
    for relative in PRESERVED_DIRECTORIES:
        assert quote(HOME + "\\" + relative.replace("/", "\\")) in script


def test_reset_records_removed_links_and_refusal_reaches_recovery():
    removed = r"C:\Users\yokeqa\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none"

    class _Control:
        home = HOME

        def __init__(self, result):
            self.result = result

        def _run(self, script, timeout=60):
            if "Get-YokeProfileProcesses).Count" in script:
                return subprocess.CompletedProcess([], 0, "YOKE_RESET_PROCESS_DISCOVERY empty", "")
            if "uv_python_registry" in script:
                return subprocess.CompletedProcess([], 0, PRISTINE, "")
            return self.result

    ok = baseline.profile_operation(
        _Control(subprocess.CompletedProcess(
            [], 0, "noise\nYOKE_RESET_LINKS_REMOVED "
            + json.dumps({"removed": [removed], "unscanned": [r"C:\long"]}) + "\n", "",
        )),
        "reset", GOLDEN,
    )
    assert ok.ok and ok.evidence["stale_links_removed"] == [removed]
    assert ok.evidence["stale_link_scan_skipped"] == [r"C:\long"]
    refused = baseline.profile_operation(
        _Control(subprocess.CompletedProcess(
            [], 1, "", "windows_reset_uv_state_left: uv-managed Python state remains at X",
        )),
        "reset", GOLDEN,
    )
    assert refused.error_code == "windows_profile_reset_failed"
    assert "windows_reset_uv_state_left" in refused.evidence["recovery"]
    assert link_sweep_record("") == {"stale_links_removed": [], "stale_link_scan_skipped": []}


def _run_powershell(tmp_path, script):
    script_file = tmp_path / "links-fixture.ps1"
    script_file.write_text("$ErrorActionPreference='Stop'\n" + script, encoding="utf-8-sig")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script_file)],
        capture_output=True, text=True, timeout=60,
    )


@pytest.mark.windows_only(reason="requires Windows junctions and robocopy")
def test_mirror_and_sweep_clear_a_dangling_uv_junction(tmp_path):
    home, golden = str(tmp_path / "profile"), str(tmp_path / "golden")
    mirror = profile_copy_script(SimpleNamespace(home=home), golden)
    sweep = stale_link_sweep_script(home, PRESERVED_DIRECTORIES)
    result = _run_powershell(tmp_path, f"$homeRoot={quote(home)}; $goldenRoot={quote(golden)}\n" + r"""
$goldenProfile=Join-Path $goldenRoot 'profile'
New-Item -ItemType Directory -Path $goldenProfile,(Join-Path $homeRoot 'Documents') -Force|Out-Null
[IO.File]::WriteAllText((Join-Path $goldenProfile 'kept.txt'),'BASELINE')
New-Item -ItemType Directory -Path (Join-Path $goldenProfile 'Documents')|Out-Null
$python=Join-Path $homeRoot 'AppData\Roaming\uv\python'
$patch=Join-Path $python 'cpython-3.12.16-windows-x86_64-none'
New-Item -ItemType Directory -Path $patch -Force|Out-Null
[IO.File]::WriteAllText((Join-Path $patch 'python.exe'),'fixture')
cmd /c mklink /J (Join-Path $python 'cpython-3.12-windows-x86_64-none') $patch|Out-Null
$system=Join-Path $homeRoot 'Documents\My Music'
cmd /c mklink /J $system (Join-Path $homeRoot 'Documents')|Out-Null
(Get-Item -LiteralPath $system -Force).Attributes='Hidden,System,ReparsePoint,Directory'
$source=$goldenProfile; $target=$homeRoot
""" + mirror + sweep + r"""
if(Test-Path -LiteralPath (Join-Path $homeRoot 'AppData\Roaming\uv')){throw 'uv state survived reset'}
if(!(Get-Item -LiteralPath $system -Force).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)){throw 'Windows junction removed'}
if([IO.File]::ReadAllText((Join-Path $homeRoot 'kept.txt')) -cne 'BASELINE'){throw 'golden file not restored'}
Write-Output 'DANGLING_UV_JUNCTION_CLEARED'
""")
    assert result.returncode == 0, result.stderr
    assert "DANGLING_UV_JUNCTION_CLEARED" in result.stdout


@pytest.mark.windows_only(reason="requires Windows junctions")
def test_sweep_removes_and_records_a_link_the_golden_lacks(tmp_path):
    home, golden = str(tmp_path / "profile"), str(tmp_path / "golden")
    sweep = stale_link_sweep_script(home, PRESERVED_DIRECTORIES)
    result = _run_powershell(tmp_path, f"$homeRoot={quote(home)}; $goldenRoot={quote(golden)}\n" + r"""
New-Item -ItemType Directory -Path $goldenRoot,(Join-Path $homeRoot 'tools\real') -Force|Out-Null
[IO.File]::WriteAllText((Join-Path $homeRoot 'tools\real\keep.txt'),'TARGET')
cmd /c mklink /J (Join-Path $homeRoot 'tools\stale') (Join-Path $homeRoot 'tools\real')|Out-Null
$source=$goldenRoot; $target=$homeRoot
""" + sweep + r"""
if(Test-Path -LiteralPath (Join-Path $homeRoot 'tools\stale')){throw 'stale link survived'}
if([IO.File]::ReadAllText((Join-Path $homeRoot 'tools\real\keep.txt')) -cne 'TARGET'){throw 'sweep followed the link'}
Write-Output 'STALE_LINK_SWEPT'
""")
    assert result.returncode == 0, result.stderr
    assert "STALE_LINK_SWEPT" in result.stdout
    [line] = [x for x in result.stdout.splitlines() if x.startswith("YOKE_RESET_LINKS_REMOVED ")]
    assert link_sweep_record(line)["stale_links_removed"] == [home + r"\tools\stale"]


@pytest.mark.windows_only(reason="requires Windows file attributes")
def test_sweep_refuses_when_uv_python_outlives_the_reset(tmp_path):
    home, golden = str(tmp_path / "profile"), str(tmp_path / "golden")
    sweep = stale_link_sweep_script(home, PRESERVED_DIRECTORIES)
    result = _run_powershell(tmp_path, f"$homeRoot={quote(home)}; $goldenRoot={quote(golden)}\n" + r"""
New-Item -ItemType Directory -Path $goldenRoot -Force|Out-Null
$python=Join-Path $homeRoot 'AppData\Roaming\uv\python'
New-Item -ItemType Directory -Path $python -Force|Out-Null
[IO.File]::WriteAllText((Join-Path $python '.lock'),'held')
$source=$goldenRoot; $target=$homeRoot
try {
""" + sweep + r"""
 throw 'uv state accepted'
} catch {
 if($_.Exception.Message -notmatch 'windows_reset_uv_state_left: .*uv\\python.*rerun yoke test-machine reset'){throw}
 Write-Output 'UV_STATE_REFUSED'
}
""")
    assert result.returncode == 0, result.stderr
    assert "UV_STATE_REFUSED" in result.stdout


def test_reset_removes_mission_scratch_the_execution_does_not_name():
    kept = HOME + r"\AppData\Local\YokeQaMission\running-walk"
    control = SimpleNamespace(home=HOME, baseline_preserved_temp_paths=(kept,))
    reset = profile_script(control, "reset", GOLDEN)
    assert "$missionRoot=" + quote(HOME + r"\AppData\Local\YokeQaMission") in reset
    assert "$missionKeep=@(" + quote(kept) + ")" in reset
    assert "windows_reset_mission_scratch_left" in reset
    assert reset.index("$sweepPreserved=") < reset.index("$missionRoot=")
    bare = profile_script(SimpleNamespace(home=HOME), "reset", GOLDEN)
    assert "$missionKeep=@()" in bare
    assert "$missionRoot=" not in profile_script(control, "capture", GOLDEN)


@pytest.mark.windows_only(reason="requires Windows junctions")
def test_stale_mission_scratch_is_removed_and_the_running_walk_kept(tmp_path):
    from yoke_harness.native_windows.mission import windows_stale_scratch_script

    root = tmp_path / "YokeQaMission"
    kept, stale = root / "running-walk", root / "aborted-walk"
    outside = tmp_path / "outside"
    script = windows_stale_scratch_script(str(root), (str(kept),))
    result = _run_powershell(tmp_path, f"$kept={quote(str(kept))}; $stale={quote(str(stale))}; $outside={quote(str(outside))}\n" + r"""
New-Item -ItemType Directory -Path $kept,$stale,$outside -Force|Out-Null
[IO.File]::WriteAllText((Join-Path $kept 'secret'),'LIVE')
[IO.File]::WriteAllText((Join-Path $stale 'secret'),'STALE')
[IO.File]::WriteAllText((Join-Path $outside 'target.txt'),'OUTSIDE')
cmd /c mklink /J (Join-Path $stale 'link') $outside|Out-Null
""" + script + r"""
if(Test-Path -LiteralPath $stale){throw 'stale scratch survived'}
if([IO.File]::ReadAllText((Join-Path $kept 'secret')) -cne 'LIVE'){throw 'running walk scratch removed'}
if([IO.File]::ReadAllText((Join-Path $outside 'target.txt')) -cne 'OUTSIDE'){throw 'removal followed a link'}
Write-Output 'STALE_SCRATCH_REMOVED'
""")
    assert result.returncode == 0, result.stderr
    assert "STALE_SCRATCH_REMOVED" in result.stdout


def test_reset_stops_profile_processes_before_the_mirror():
    from yoke_harness.native_windows.profile_processes import stopped_processes

    reset = profile_script(SimpleNamespace(home=HOME), "reset", GOLDEN)
    assert reset.index("$stopPreserved=") < reset.index("robocopy.exe")
    assert "windows_reset_profile_process_running" in reset
    assert quote(HOME + r"\AppData\Local\Microsoft") in reset
    assert "$stopPreserved" not in profile_script(SimpleNamespace(home=HOME), "capture", GOLDEN)
    exe = HOME + r"\AppData\Roaming\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe"
    assert stopped_processes("YOKE_RESET_PROCESSES_STOPPED " + json.dumps([exe])) == [exe]
    assert stopped_processes("") == []


@pytest.mark.windows_only(reason="requires Windows processes")
def test_profile_process_is_stopped_and_preserved_app_keeps_running(tmp_path):
    from yoke_harness.native_windows.profile_processes import profile_process_stop_script

    home = str(tmp_path / "profile")
    stop = profile_process_stop_script(home, PRESERVED_DIRECTORIES)
    result = _run_powershell(tmp_path, f"$profileRoot={quote(home)}\n" + r"""
$tool=Join-Path $profileRoot 'AppData\Roaming\uv\python\fixture'
$app=Join-Path $profileRoot 'AppData\Local\Microsoft\fixture'
New-Item -ItemType Directory -Path $tool,$app -Force|Out-Null
Copy-Item "$env:SystemRoot\System32\PING.EXE" (Join-Path $tool 'held.exe')
Copy-Item "$env:SystemRoot\System32\PING.EXE" (Join-Path $app 'live.exe')
$held=Start-Process -FilePath (Join-Path $tool 'held.exe') -ArgumentList '-n','120','127.0.0.1' -WindowStyle Hidden -PassThru
$live=Start-Process -FilePath (Join-Path $app 'live.exe') -ArgumentList '-n','120','127.0.0.1' -WindowStyle Hidden -PassThru
try {
""" + stop + r"""
 if(Get-Process -Id $held.Id -ErrorAction SilentlyContinue){throw 'profile process survived'}
 if(!(Get-Process -Id $live.Id -ErrorAction SilentlyContinue)){throw 'preserved app stopped'}
 Remove-Item -LiteralPath (Join-Path $tool 'held.exe') -Force
 Write-Output 'PROFILE_PROCESS_STOPPED'
} finally {Stop-Process -Id $live.Id,$held.Id -Force -ErrorAction SilentlyContinue}
""")
    assert result.returncode == 0, result.stderr
    assert "PROFILE_PROCESS_STOPPED" in result.stdout
    assert "held.exe" in result.stdout


@pytest.mark.parametrize("phase", ["listing_failed", "running"])
def test_process_stop_failure_refuses_before_mirroring(monkeypatch, phase):
    def listing(script, **kwargs):
        assert "Get-YokeProfileProcesses).Count" in script
        return subprocess.CompletedProcess([], 1, "", "Access denied ") if phase == "listing_failed" else subprocess.CompletedProcess([], 0, "YOKE_RESET_PROCESS_DISCOVERY present", "")
    def stuck(control, script, *, timeout=60, hidden=False):
        assert phase == "running"
        return subprocess.CompletedProcess([], 1, "", "Access denied ")

    monkeypatch.setattr("yoke_harness.native_windows.desktop.desktop_script", stuck)
    refused = baseline.profile_operation(SimpleNamespace(home=HOME, _run=listing), "reset", GOLDEN)
    assert refused.error_code == "windows_reset_profile_process_" + phase
    assert "Access denied." in refused.evidence["recovery"]


def test_mirror_excludes_the_live_windows_data_store_and_names_copy_errors():
    mirror = profile_copy_script(SimpleNamespace(home=HOME), GOLDEN)
    assert quote(HOME + r"\AppData\Local\Comms") in mirror
    assert quote(GOLDEN + r"\profile\AppData\Local\Comms") in mirror
    assert "Select-String -LiteralPath $copyLog -Pattern 'ERROR" in mirror
    assert "($copyErrors -join ' | ')" in mirror
    assert "ERROR (32|1224)" in mirror
    assert "Close Codex in the signed-in test session" in mirror


def test_mirror_keeps_windows_profile_compatibility_junctions():
    mirror = profile_copy_script(SimpleNamespace(home=HOME), GOLDEN)
    walk, robocopy = mirror.index("$walk.Push($target)"), mirror.index("robocopy.exe")
    assert walk < robocopy
    assert "[IO.FileAttributes]::System) -and" in mirror
    assert "$exclude+=$entry.FullName" in mirror


@pytest.mark.windows_only(reason="requires Windows PowerShell")
@pytest.mark.parametrize("desktop", [False, True])
@pytest.mark.parametrize("daemon_args", [
    "app-server --listen unix:// --managed-daemon",
    "app-server --listen unix:// --analytics-default-enabled --managed-daemon",
    "app-server --remote-control --listen unix:// --analytics-default-enabled "
    "-c features.example=true -c features.other=false --managed-daemon",
])
def test_reset_stops_only_eligible_processes(tmp_path, monkeypatch, desktop, daemon_args):
    from yoke_harness.native_windows import profile_processes as processes

    monkeypatch.setattr(processes, "_PROCESS_IDENTITY", "")

    result = _run_powershell(tmp_path, rf"""
$profileRoot={quote(HOME)}
$env:ProgramFiles='C:\Program Files'
$includeOtherSession={"$true" if desktop else "$false"}
$daemonArgs={quote(daemon_args)}
""" + r"""
$packageRoot=Join-Path $env:ProgramFiles 'WindowsApps\Codex_fixture'
$codex=Join-Path $packageRoot 'app\Codex.exe'
$claude=Join-Path $profileRoot 'AppData\Local\Programs\Claude.exe'
$preserved=Join-Path $profileRoot 'AppData\Local\Microsoft\Keep.exe'
$other=Join-Path $packageRoot 'Other.exe'
$daemon=Join-Path $profileRoot '.codex\packages\app-server-daemon\releases\0.172.0-x86_64-pc-windows-msvc\bin\codex.exe'
$standalone=Join-Path $profileRoot '.codex\packages\standalone\current\bin\codex.exe'
$entries=@()
foreach($path in @($codex,$claude,$preserved,$other,$daemon,$daemon,$daemon,$daemon,$standalone,$daemon)){
 $entries+= [pscustomobject]@{Id=$entries.Count+1;Path=$path;SessionId=1;MainWindowHandle=1;HasExited=$false}
}
$entries[7].SessionId=2
function Get-Process($Id){
 if($Id -eq $PID){@{SessionId=1}; return}
 $entries | Where-Object {!$_.HasExited -and ($includeOtherSession -or $_.SessionId -eq 1)}
}
function Get-YokeOwnedCommandLine($processId,$image){
 if($processId -eq 6){return ('"'+$image+'" app-server daemon pid-update-loop')}
 if($processId -eq 7){return ('"'+$image+'" app-server --listen unix:// --analytics-default-enabled')}
 if($processId -eq 10){return ('"'+$image+'" app-server --listen unix:// --analytics-default-enabled -c other.example=true --managed-daemon')}
 '"'+$image+'" '+$daemonArgs
}
function Get-YokeOwnedExecutable($processId){
 if($processId -ne 4){$entries[$processId-1].Path}
}
function Get-AppxPackage {@{InstallLocation=$packageRoot;PackageFamilyName='Codex_fixture'}}
function Get-AppxPackageManifest($Package) {
 [xml]'<Package><Applications><Application Id="App" Executable="app\Codex.exe"/></Applications></Package>'
}
function Stop-Process($InputObject,[switch]$Force){$InputObject.HasExited=$true}
""" + processes.profile_process_stop_script(HOME, PRESERVED_DIRECTORIES, desktop=desktop) + r"""
if(!$entries[4].HasExited -or !$entries[5].HasExited){throw 'daemon still running'}
foreach($index in @(2,3,6,7,8,9)){
 if($entries[$index].HasExited){throw 'excluded process stopped'}
}
""")
    assert result.returncode == 0, result.stderr
    stopped = processes.stopped_processes(result.stdout)
    assert stopped[:2] == [
        r"C:\Program Files\WindowsApps\Codex_fixture\app\Codex.exe",
        HOME + r"\AppData\Local\Programs\Claude.exe",
    ]
    assert len(stopped[2:]) == 2
    assert all(r"\packages\app-server-daemon\releases" in path for path in stopped[2:])
    if not desktop:
        assert processes.TARGETS_MARKER not in result.stdout
        return
    targets = next(
        json.loads(line[len(processes.TARGETS_MARKER):])
        for line in result.stdout.splitlines() if line.startswith(processes.TARGETS_MARKER)
    )
    assert [app["path"] for app in targets] == stopped[:2]
    assert [app["target"] for app in targets] == [
        r"shell:AppsFolder\Codex_fixture!App", HOME + r"\AppData\Local\Programs\Claude.exe",
    ]
