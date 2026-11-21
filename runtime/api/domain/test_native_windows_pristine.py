"""Native Windows goldens hold no Yoke stage folders or uv Python registry entry."""

import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from yoke_harness.native_windows import baseline
from yoke_harness.native_windows.baseline import profile_copy_script, profile_script
from yoke_harness.native_windows.pristine import (
    RESIDUE_CLEANUP, STAGE_COPY_EXCLUSION, UV_PYTHON_REGISTRY, residue_script,
)
from yoke_harness.native_windows.transport import quote

pytestmark = pytest.mark.windows

HOME = r"C:\Users\yokeqa"
GOLDEN = r"D:\goldens\fixture"
PRISTINE = json.dumps({"stage_folders": [], "uv_python_registry": False})
RESIDUE = [
    {"stage_folders": [".yoke-stage-" + "a" * 32], "uv_python_registry": False},
    {"stage_folders": ".yoke-stage-" + "b" * 32, "uv_python_registry": False},
    {"stage_folders": [], "uv_python_registry": True},
]


def _probe_answer(answer, calls):
    def run(script, timeout=60):
        calls.append(script)
        if "uv_python_registry" in script:
            return subprocess.CompletedProcess([], 0, answer, "")
        if "Get-YokeProfileProcesses).Count" in script:
            return subprocess.CompletedProcess([], 0, "YOKE_RESET_PROCESS_DISCOVERY empty", "")
        return subprocess.CompletedProcess([], 0, "", "")
    return SimpleNamespace(home=HOME, _run=run)


def test_profile_mirror_excludes_root_stage_folders_in_both_directions():
    mirror = profile_copy_script(SimpleNamespace(home=HOME), GOLDEN)
    assert STAGE_COPY_EXCLUSION in mirror
    assert "foreach($root in @($source,$target))" in STAGE_COPY_EXCLUSION
    assert "-Filter '.yoke-stage-*'" in STAGE_COPY_EXCLUSION
    for operation in ("capture", "reset"):
        script = profile_script(SimpleNamespace(home=HOME), operation, GOLDEN)
        assert script.index(STAGE_COPY_EXCLUSION) < script.index("robocopy.exe")


@pytest.mark.parametrize("residue", RESIDUE)
def test_capture_refuses_a_profile_with_stage_folders_or_uv_registry(residue):
    calls = []
    refused = baseline.profile_operation(_probe_answer(json.dumps(residue), calls), "capture", GOLDEN)
    assert refused.error_code == "windows_profile_not_pristine"
    stages = residue["stage_folders"]
    assert refused.evidence["profile_residue"] == {
        "stage_folders": [stages] if isinstance(stages, str) else stages,
        "uv_python_registry": residue["uv_python_registry"],
    }
    assert "yoke test-machine reset" in refused.evidence["recovery"]
    assert len(calls) == 1 and "robocopy.exe" not in calls[0]


def test_pristine_capture_runs_the_copy():
    calls = []
    captured = baseline.profile_operation(_probe_answer(PRISTINE, calls), "capture", GOLDEN)
    assert captured.ok, captured.evidence
    assert "robocopy.exe" in calls[1]


@pytest.mark.parametrize("residue", RESIDUE)
def test_reset_absence_proof_fails_on_stage_folders_or_uv_registry(residue):
    calls = []
    failed = baseline.profile_operation(_probe_answer(json.dumps(residue), calls), "reset", GOLDEN)
    assert failed.error_code == "windows_profile_not_pristine"
    assert failed.evidence["profile_residue"]["uv_python_registry"] is residue["uv_python_registry"]
    assert failed.evidence["golden_baseline_path"] == GOLDEN
    assert "robocopy.exe" in calls[-2] and "uv_python_registry" in calls[-1]


@pytest.mark.parametrize("answer", [
    subprocess.CompletedProcess([], 1, "", "Access denied"),
    subprocess.CompletedProcess([], 0, "not json", ""),
])
def test_unanswered_residue_probe_is_not_pristine(answer):
    control = SimpleNamespace(home=HOME, _run=lambda script, timeout=60: answer)
    refused = baseline.profile_operation(control, "capture", GOLDEN)
    assert refused.error_code == "windows_profile_residue_unproved"
    assert refused.evidence["recovery"]


def test_reset_removes_other_stage_folders_and_uv_registry_after_the_mirror():
    reset = profile_script(SimpleNamespace(home=HOME), "reset", GOLDEN)
    assert reset.index("robocopy.exe") < reset.index(RESIDUE_CLEANUP) < reset.index("Restore-YokeUserPath $pathKey")
    assert "$ownStage=" in RESIDUE_CLEANUP and "Split-Path -Parent $PSCommandPath" in RESIDUE_CLEANUP
    assert f"Remove-Item -LiteralPath '{UV_PYTHON_REGISTRY}' -Recurse -Force" in RESIDUE_CLEANUP
    assert RESIDUE_CLEANUP not in profile_script(SimpleNamespace(home=HOME), "capture", GOLDEN)


@pytest.mark.windows_only(reason="requires Windows robocopy and the registry")
def test_stage_folders_stay_out_of_goldens_and_reset_keeps_only_its_own(tmp_path):
    home, golden = str(tmp_path / "profile"), str(tmp_path / "golden")
    # A fixture key stands in for uv's, so the runner's own registry stays intact.
    fixture_key = r"HKCU:\Software\YokeQaFixture-" + uuid4().hex
    registry = fixture_key + r"\Astral"
    mirror = profile_copy_script(SimpleNamespace(home=home), golden)
    cleanup = RESIDUE_CLEANUP.replace(UV_PYTHON_REGISTRY, registry)
    probe = residue_script(home).replace(UV_PYTHON_REGISTRY, registry)
    own = tmp_path / "profile" / (".yoke-stage-" + "1" * 32)
    own.mkdir(parents=True)
    script = own / "script.ps1"
    script.write_text(
        "$ErrorActionPreference='Stop'\n"
        f"$profileRoot={quote(home)}; $goldenProfile={quote(golden + chr(92) + 'profile')}\n"
        + r"""
$other=Join-Path $profileRoot ('.yoke-stage-'+('2'*32))
New-Item -ItemType Directory -Path $other | Out-Null
[IO.File]::WriteAllText((Join-Path $other 'script.ps1'),'stale')
[IO.File]::WriteAllText((Join-Path $profileRoot 'ordinary.txt'),'BASELINE')
$source=$profileRoot; $target=$goldenProfile
""" + mirror + r"""
if(@(Get-ChildItem -LiteralPath $goldenProfile -Force -Filter '.yoke-stage-*').Count){throw 'stage folder captured'}
if(!(Test-Path -LiteralPath (Join-Path $goldenProfile 'ordinary.txt'))){throw 'ordinary file not captured'}
New-Item -Path 'REGISTRY' -Force | Out-Null
$source=$goldenProfile; $target=$profileRoot
""".replace("REGISTRY", registry) + mirror + r"""
if(!(Test-Path -LiteralPath $other)){throw 'reset mirror purged a stage folder it should leave to cleanup'}
""" + probe + "\n" + cleanup + r"""
if(Test-Path -LiteralPath $other){throw 'stale stage folder kept'}
if(!(Test-Path -LiteralPath $PSCommandPath)){throw 'running stage folder removed'}
""" + probe + "\n",
        encoding="utf-8-sig",
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script)],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        f"Remove-Item -LiteralPath {quote(fixture_key)} -Recurse -Force -ErrorAction SilentlyContinue"])
    assert result.returncode == 0, result.stderr
    before, after = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert before["uv_python_registry"] is True and len(before["stage_folders"]) == 2
    kept = after["stage_folders"]
    assert ([kept] if isinstance(kept, str) else kept) == [own.name]
    assert after["uv_python_registry"] is False


@pytest.mark.parametrize("relaunch_fails,residue", [
    (False, PRISTINE), (True, PRISTINE), (False, json.dumps({"stage_folders": "x", "uv_python_registry": False})),
])
def test_reset_ends_desktop_session_processes_before_mirroring(monkeypatch, relaunch_fails, residue):
    from yoke_harness.native_windows import profile_processes as processes

    packaged = r"C:\Program Files\WindowsApps\Codex_1\app\Codex.exe"
    installed = HOME + r"\AppData\Local\Programs\Claude\Claude.exe"
    aumid = r"shell:AppsFolder\Codex_fixture!App"
    targets = [{"target": aumid, "path": packaged}, {"target": installed, "path": installed}]
    calls = []

    class _Control:
        home = HOME

        def _run(self, script, timeout=60):
            if "uv_python_registry" in script:
                calls.append("residue")
                return subprocess.CompletedProcess([], 0, residue, "")
            listing = "Get-YokeProfileProcesses).Count" in script
            calls.append("list" if listing else "reset")
            return subprocess.CompletedProcess([], 0, "YOKE_RESET_PROCESS_DISCOVERY present" if listing else "", "")

    def desktop(control, script, *, timeout=60, hidden=False):
        assert hidden
        if "Stop-Process" in script:
            calls.append("stop")
            assert "Get-AppxPackageManifest" in script
            assert script.index("Get-AppxPackageManifest") < script.index("Stop-Process -InputObject")
            output = processes.STOPPED_MARKER + json.dumps([packaged, installed]) + "\n"
            output += processes.TARGETS_MARKER + json.dumps([*targets, targets[0]])
        else:
            calls.append("relaunch")
            assert script.count(json.dumps(aumid)) == 1
            output = "\n".join(
                processes.RELAUNCHED_MARKER + json.dumps({"target": app["target"], "failure": error})
                for app, error in zip(targets, ["activation failed" if relaunch_fails else "", ""])
            )
        return subprocess.CompletedProcess([], 0, output, "")

    monkeypatch.setattr("yoke_harness.native_windows.desktop.desktop_script", desktop)
    result = baseline.profile_operation(_Control(), "reset", GOLDEN)
    # Residue fails the reset only after the stopped desktop apps come back.
    assert calls == ["list", "stop", "reset", "residue", "relaunch"]
    assert result.ok is (residue == PRISTINE) and result.evidence["profile_processes_stopped"] == [packaged, installed]
    assert result.evidence["desktop_apps_relaunched"] == ([installed] if relaunch_fails else [aumid, installed])
    assert result.evidence["desktop_apps_relaunch_failed"] == (
        [{"target": aumid, "failure": "activation failed"}] if relaunch_fails else []
    )
