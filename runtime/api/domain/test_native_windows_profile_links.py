"""Reset removes links the golden lacks and proves no uv-managed Python is left."""

import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness.native_windows import baseline
from yoke_harness.native_windows.baseline import (
    PRESERVED_DIRECTORIES, profile_copy_script, profile_script,
)
from yoke_harness.native_windows.profile_links import (
    removed_links, stale_link_sweep_script,
)
from yoke_harness.native_windows.transport import quote

pytestmark = pytest.mark.windows

HOME = r"C:\Users\yokeqa"
GOLDEN = r"D:\goldens\fixture"


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
            return self.result

    ok = baseline.profile_operation(
        _Control(subprocess.CompletedProcess(
            [], 0, "noise\nYOKE_RESET_LINKS_REMOVED " + '["' + removed.replace("\\", "\\\\") + '"]\n', "",
        )),
        "reset", GOLDEN,
    )
    assert ok.ok and ok.evidence["stale_links_removed"] == [removed]
    refused = baseline.profile_operation(
        _Control(subprocess.CompletedProcess(
            [], 1, "", "windows_reset_uv_state_left: uv-managed Python state remains at X",
        )),
        "reset", GOLDEN,
    )
    assert refused.error_code == "windows_profile_reset_failed"
    assert "windows_reset_uv_state_left" in refused.evidence["recovery"]
    assert removed_links("") == []


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
    [line] = [x for x in result.stdout.splitlines() if x.startswith("YOKE_RESET_LINKS_REMOVED ")]
    assert removed_links(line) == [
        home + r"\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none"
    ]


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
