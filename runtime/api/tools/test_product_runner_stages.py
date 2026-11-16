"""Stage cutoff, the not-set-up status proof, and the Windows child environment."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_cutoff_runs_earlier_stages_in_order_and_skips_cleanup(tmp_path, monkeypatch):
    seen = []
    fake = tuple((name, lambda run, name=name: seen.append(name)) for name in stages.STAGE_NAMES)
    monkeypatch.setattr(smoke, "STAGES", fake)
    commands = Commands(tmp_path, {})
    run = stages.SmokeRun(tmp_path, tmp_path, commands, {})
    monkeypatch.setattr(smoke, "cleanup", lambda *args, **kwargs: pytest.fail("cleanup"))
    smoke.run_stages(run, "status")
    assert seen == ["install", "status"]
    assert run.report == {"stage": "status", "ok": True}


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
        smoke.run_stages(run, "onboard")


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
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP")
    )
    assert env["PATH"].split(smoke.os.pathsep)[0] == str(tmp_path / "venv" / "Scripts")
