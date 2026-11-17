"""Stage order and cleanup, the not-set-up status proof, and the Windows child environment."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.tools import product_runner_hooks as hooks
from runtime.api.tools import product_runner_smoke as smoke
from runtime.api.tools import product_runner_stages as stages
from runtime.api.tools.product_runner_commands import Commands, SmokeFailure


pytestmark = pytest.mark.windows


def _run(tmp_path: Path, monkeypatch, stdout: str, returncode: int = 1):
    monkeypatch.setattr(
        "runtime.api.tools.product_runner_commands.subprocess.run",
        lambda argv, **kwargs: SimpleNamespace(
            returncode=returncode if "status" in argv else 0,
            stdout=stdout if "status" in argv else "yoke 1.0\n",
            stderr="",
        ),
    )
    home = tmp_path / "home"
    output = tmp_path / "evidence"
    output.mkdir()
    commands = Commands(output, {"HOME": str(home)})
    return stages.SmokeRun(tmp_path, tmp_path, commands, {})


def _status(home: Path, codes=("config_missing",), ok=False) -> str:
    issues = [{"code": code} for code in codes]
    return json.dumps(
        {"ok": ok, "config_path": str(home / ".yoke/config.json"), "issues": issues}
    )


def test_status_stage_accepts_the_named_not_set_up_answer(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, _status(tmp_path / "home"))
    stages.status(run)
    assert run.report["status_issues"] == ["config_missing"]


@pytest.mark.parametrize(
    ("codes", "ok", "returncode", "reason"),
    [
        ((), False, 1, "status_not_unset"),
        (("config_missing",), True, 1, "status_not_unset"),
        (("config_missing",), False, 0, "command_failed"),
    ],
)
def test_status_stage_refuses_any_other_answer(
    tmp_path, monkeypatch, codes, ok, returncode, reason
):
    run = _run(tmp_path, monkeypatch, _status(tmp_path / "home", codes, ok), returncode)
    with pytest.raises(SmokeFailure, match=f"{reason}: step=yoke-status"):
        stages.status(run)


def test_status_stage_refuses_a_config_outside_the_isolated_home(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, _status(tmp_path / "elsewhere"))
    with pytest.raises(SmokeFailure, match="status_config_outside_home"):
        stages.status(run)


def test_every_stage_runs_in_order_then_cleanup_stops_what_the_smoke_started(
    tmp_path, monkeypatch
):
    seen = []

    def stage(run, name):
        seen.append(name)
        run.onboarded = run.onboarded or name == "onboard"

    fake = tuple((name, lambda run, name=name: stage(run, name)) for name in stages.STAGE_NAMES)
    monkeypatch.setattr(smoke, "STAGES", fake)
    run = stages.SmokeRun(tmp_path, tmp_path, Commands(tmp_path, {}), {})
    monkeypatch.setattr(run.commands, "run", lambda name, argv, **kwargs: seen.append(argv[1:3]))
    smoke.run_stages(run)
    assert seen == [
        *stages.STAGE_NAMES,
        ["hook", "resident"],
        ["relay", "uninstall"],
        ["local-postgres", "stop"],
    ]
    assert run.report == {"stage": "source-tests", "ok": True}


def test_cleanup_failure_cannot_hide_the_primary_failure(tmp_path, monkeypatch):
    def onboard(run):
        run.onboarded = True
        raise SmokeFailure("onboard_not_born: step=onboard: inspect capture")

    monkeypatch.setattr(smoke, "STAGES", (("onboard", onboard),))
    run = stages.SmokeRun(tmp_path, tmp_path, Commands(tmp_path, {}), {})
    monkeypatch.setattr(
        run.commands, "run", lambda *a, **k: (_ for _ in ()).throw(SmokeFailure("x"))
    )
    with pytest.raises(SmokeFailure, match="onboard_not_born"):
        smoke.run_stages(run)


def test_windows_child_environment_is_isolated_and_startable(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "WINDOWS", True)
    monkeypatch.setattr(smoke, "venv_executable", lambda venv, name: venv / "Scripts" / f"{name}.exe")
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("GH_TOKEN", "host-token")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\host\AppData\Local")
    env = smoke.isolated_environment(tmp_path, tmp_path / "venv")
    home = tmp_path / "home"
    assert env["SYSTEMROOT"] == r"C:\Windows"
    assert "GH_TOKEN" not in env and "SHELL" not in env
    assert all(
        Path(env[name]).is_relative_to(home)
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA")
    )
    assert env["TEMP"] == env["TMP"] == str(tmp_path / "tmp")
    assert env["PATH"].split(smoke.os.pathsep)[0] == str(tmp_path / "venv" / "Scripts")
    powershell = Path(r"C:\Windows") / "System32" / "WindowsPowerShell" / "v1.0"
    assert env["PATH"].endswith(smoke.os.pathsep + str(powershell))


@pytest.mark.parametrize("windows", [True, False])
def test_replay_runs_the_command_the_native_harness_runs_on_this_os(tmp_path, windows):
    handler = {"command": "/bin/sh -c 'yoke hook evaluate PreToolUse'"}
    handler["commandWindows"] = "powershell.exe -EncodedCommand AAAA"
    config = tmp_path / "hooks.json"
    config.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [handler]}]}}))
    expected = handler["commandWindows" if windows else "command"]
    assert hooks.rendered_command(tmp_path, "hooks.json", "PreToolUse", windows=windows) == expected


def test_scratch_home_socket_fits_under_the_windows_runner_temp_folder():
    # The hosted runner's temp folder plus TemporaryDirectory's 8 random
    # characters, then the local universe's socket under the scratch HOME.
    scratch = r"C:\Users\runneradmin\AppData\Local\Temp" + "\\" + smoke.SCRATCH_PREFIX + "x" * 8
    socket = scratch + r"\home\.yoke\local-universe\sock\.s.PGSQL.5432"
    assert len(socket) <= 103  # postgres_cluster's macOS/Windows sun_path budget


@pytest.mark.parametrize("primary_failure", [True, False])
def test_failed_relay_removal_still_stops_postgres(tmp_path, monkeypatch, primary_failure):
    run = stages.SmokeRun(tmp_path, tmp_path, Commands(tmp_path, {}), {})
    seen = []

    def command(name, argv, **kwargs):
        seen.append(name)
        if name == "uninstall-local-relay":
            raise SmokeFailure("relay_task_scheduler_unavailable: step=uninstall-local-relay")

    monkeypatch.setattr(run.commands, "run", command)
    if primary_failure:
        smoke.cleanup(run, primary_failure=True)
    else:
        with pytest.raises(SmokeFailure, match="relay_task_scheduler_unavailable"):
            smoke.cleanup(run, primary_failure=False)
    assert seen == ["stop-hook-resident", "uninstall-local-relay", "stop-local-postgres"]


@pytest.mark.parametrize("primary_failure", [True, False])
def test_held_scratch_folder_never_hides_the_primary_failure(tmp_path, monkeypatch, primary_failure):
    def held(path):
        raise PermissionError(32, "The process cannot access the file", str(path))

    monkeypatch.setattr(smoke.shutil, "rmtree", lambda path, **handler: held(path))
    report = {}
    if primary_failure:
        smoke.remove_scratch(tmp_path, report, primary_failure=True)
        assert report["scratch_cleanup_failure"].startswith("scratch_cleanup_failed")
    else:
        with pytest.raises(SmokeFailure, match="scratch_cleanup_failed"):
            smoke.remove_scratch(tmp_path, report, primary_failure=False)


def test_scratch_removal_deletes_read_only_files(tmp_path):
    scratch = tmp_path / "scratch"
    (scratch / ".git" / "objects").mkdir(parents=True)
    obj = scratch / ".git" / "objects" / "0a"
    obj.write_text("object", encoding="utf-8")
    obj.chmod(0o444)  # Git's object files are read-only; Windows refuses to delete them
    smoke.remove_scratch(scratch, {}, primary_failure=False)
    assert not scratch.exists()
