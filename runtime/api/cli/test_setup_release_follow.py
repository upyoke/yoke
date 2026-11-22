"""Setup installs the served release under its lock and resumes the same run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import onboard, onboard_apply
from yoke_cli.config import onboard_apply_lock, onboard_wizard, setup_release_follow
from yoke_cli.config import writer
from yoke_cli.config.onboard_wizard_flow_apply import ApplyFlow
from yoke_cli.project_install.validate import CliReleaseMismatch

RUNNING = "0.2.0.202611211930"
SERVED = "0.2.0.202611212023"
OLDER = "0.2.0.202611201926"
STEP = "project-install-scaffold"


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    config = tmp_path / "home" / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(config.parent))
    monkeypatch.delenv(setup_release_follow.FOLLOWED_RUN_ENV, raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    writer.set_connection(
        "test", transport="https", api_url="https://test.invalid",
        token="fixture", path=config,
    )
    writer.set_active_env("test", path=config)
    installs: list[str] = []

    def install_release(target, yoke_bin, **_kwargs):
        # The relay's follow takes this same lock, so it must be held here.
        assert onboard_apply_lock.lock_path().is_file()
        installs.append(target.version)
        return target.version

    follow = setup_release_follow
    monkeypatch.setattr(follow.shutil, "which", lambda _name: "/bin/yoke")
    monkeypatch.setattr(
        follow.install_binding, "require_packaged_install", lambda _c: {"version": RUNNING}
    )
    monkeypatch.setattr(
        follow.self_update, "resolve_target",
        lambda *, version: argparse.Namespace(version=version),
    )
    monkeypatch.setattr(follow.self_update, "install_release", install_release)
    return {"config": str(config), "installs": installs}


def _apply(monkeypatch, machine, *, served=SERVED, resume=None, **extra) -> dict:
    seen: dict = {}

    def build_report(**kwargs):
        progress = kwargs.get("progress")
        if progress is None:
            return {"plan": {"project": None, "steps": [{"action": STEP, "target": ""}]}}
        seen["lock"] = json.loads(onboard_apply_lock.lock_path().read_text("utf-8"))
        progress(STEP, "", "running")
        if served != RUNNING:
            target = served if served[:1].isdigit() else None
            raise CliReleaseMismatch(RUNNING, served, target)
        progress(STEP, "", "done")
        return {"project_onboarding": {}}

    monkeypatch.setattr(onboard_apply.onboard_config, "build_report", build_report)
    kwargs = {
        "apply": True, "path_repair": {}, "config_path": machine["config"],
        "env_name": "test", **extra,
    }
    if resume is not None:
        payload = json.loads(Path(resume).read_text("utf-8"))
        kwargs.update(resume_run_id=payload["run_id"], resume_payload=payload)
    report = onboard_apply.apply_with_durable_report(kwargs, install_health=False)
    return {**report, "seen_lock": seen["lock"]}


def _follow(monkeypatch, machine, **extra) -> setup_release_follow.ReleaseFollowed:
    with pytest.raises(setup_release_follow.ReleaseFollowed) as exc:
        _apply(monkeypatch, machine, **extra)
    return exc.value


def _report(run_id: str) -> dict:
    from yoke_cli.config import onboard_apply_report

    return json.loads(onboard_apply_report.run_report_path(run_id).read_text("utf-8"))


def test_mismatch_installs_served_release_then_resumed_run_completes(
    monkeypatch, machine
):
    followed = _follow(monkeypatch, machine)

    assert machine["installs"] == [SERVED]
    assert (followed.running, followed.served) == (RUNNING, SERVED)
    assert not onboard_apply_lock.lock_path().exists()  # released before re-exec
    payload = _report(followed.run_id)
    assert payload["final_status"] == setup_release_follow.FINAL_STATUS
    assert payload["cli_followed_release"] == {"from": RUNNING, "to": SERVED}

    monkeypatch.setenv(setup_release_follow.FOLLOWED_RUN_ENV, followed.run_id)
    from yoke_cli.config import onboard_apply_report

    path = onboard_apply_report.run_report_path(followed.run_id)
    report = _apply(monkeypatch, machine, served=RUNNING, resume=path)

    assert report["seen_lock"]["run_id"] == followed.run_id
    assert report["cli_followed_release"] == {"from": RUNNING, "to": SERVED}
    assert _report(followed.run_id)["final_status"] == "done"
    assert _report(followed.run_id)["cli_followed_release"]["to"] == SERVED
    assert machine["installs"] == [SERVED]


def test_resumed_run_still_mismatched_refuses_without_second_install(
    monkeypatch, machine
):
    followed = _follow(monkeypatch, machine)
    monkeypatch.setenv(setup_release_follow.FOLLOWED_RUN_ENV, followed.run_id)
    from yoke_cli.config import onboard_apply_report

    path = onboard_apply_report.run_report_path(followed.run_id)
    with pytest.raises(onboard_wizard.WizardApplyError) as exc:
        _apply(monkeypatch, machine, resume=path)

    assert "setup_bundle_version_mismatch" in str(exc.value)
    assert "already installed a release once" in str(exc.value)
    assert machine["installs"] == [SERVED]


def test_older_served_release_on_active_connection_is_followed(monkeypatch, machine):
    # The active relay drives the CLI to its server's release either way.
    followed = _follow(monkeypatch, machine, served=OLDER)

    assert followed.served == OLDER
    assert machine["installs"] == [OLDER]


@pytest.mark.parametrize(
    ("extra", "cause"),
    [
        ({"token_source_kind": "stdin"}, "came from stdin"),
        ({"env_name": "other"}, "is not this machine's active connection"),
        ({"served": "not-a-release"}, "downloadable CLI release"),
    ],
)
def test_unfollowable_mismatch_refuses_without_installing(
    monkeypatch, machine, extra, cause
):
    with pytest.raises(onboard_wizard.WizardApplyError) as exc:
        _apply(monkeypatch, machine, **extra)

    assert "setup_bundle_version_mismatch" in str(exc.value)
    assert cause in str(exc.value)
    assert machine["installs"] == []


def test_source_checkout_refuses_with_update_recovery(monkeypatch, machine):
    def source(_command):
        raise setup_release_follow.install_binding.SourceCheckoutError("source checkout")

    monkeypatch.setattr(
        setup_release_follow.install_binding, "require_packaged_install", source
    )
    with pytest.raises(onboard_wizard.WizardApplyError) as exc:
        _apply(monkeypatch, machine)

    assert "setup_bundle_version_mismatch" in str(exc.value)
    assert f"yoke update --version {SERVED}" in str(exc.value)
    assert machine["installs"] == []


@pytest.mark.parametrize(
    "error",
    ["the Yoke installer failed (exit 1): boom", "`yoke --version` reports 'x'"],
)
def test_install_failure_refuses_with_update_recovery(monkeypatch, machine, error):
    def fail(_target, _yoke_bin, **_kwargs):
        raise setup_release_follow.self_update.SelfUpdateError(error)

    monkeypatch.setattr(setup_release_follow.self_update, "install_release", fail)
    with pytest.raises(onboard_wizard.WizardApplyError) as exc:
        _apply(monkeypatch, machine)

    text = str(exc.value)
    assert "setup_bundle_version_mismatch" in text and error in text
    assert f"yoke update --version {SERVED}" in text
    assert "resume this setup run" in text


def test_setup_command_reexecs_resume_with_original_mode_flags(monkeypatch):
    followed = setup_release_follow.ReleaseFollowed("run-1", RUNNING, SERVED, "/bin/yoke")

    def raise_followed(_parsed):
        raise followed

    calls = []
    monkeypatch.setattr(onboard, "_onboard", raise_followed)
    monkeypatch.setattr(setup_release_follow.os, "name", "posix")
    monkeypatch.setattr(
        setup_release_follow.os, "execve",
        lambda path, argv, env: calls.append((path, argv, env)),
    )
    onboard.onboard(["--json", "--non-interactive", "--yes", "--config", "/c.json"])

    path, argv, env = calls[0]
    assert path == "/bin/yoke"
    assert argv == [
        "/bin/yoke", "setup", "--resume", "run-1",
        "--json", "--non-interactive", "--yes", "--config", "/c.json",
    ]
    assert env[setup_release_follow.FOLLOWED_RUN_ENV] == "run-1"


def test_agent_mode_flag_is_forwarded():
    parsed = argparse.Namespace(agent=True, apply=False)
    assert setup_release_follow.mode_flags(parsed) == ["--agent"]


def test_windows_runs_resumed_setup_as_child_and_returns_its_code(monkeypatch):
    followed = setup_release_follow.ReleaseFollowed("run-2", RUNNING, SERVED, "yoke.cmd")
    monkeypatch.setattr(setup_release_follow.os, "name", "nt")
    seen = []

    def run(argv, *, env, check):
        seen.append(argv)
        return argparse.Namespace(returncode=7)

    monkeypatch.setattr(setup_release_follow.subprocess, "run", run)
    code = setup_release_follow.resume(followed, argparse.Namespace(apply=True))

    assert code == 7
    assert seen == [["yoke.cmd", "setup", "--resume", "run-2", "--yes"]]


def test_shell_closes_and_keeps_follow_for_its_runner():
    followed = setup_release_follow.ReleaseFollowed("run-3", RUNNING, SERVED, "/bin/yoke")

    class Shell(ApplyFlow):
        exited = False

        def exit(self):
            self.exited = True

    shell = Shell()
    shell._finish_apply(None, followed)

    assert shell.exited and shell.release_followed is followed
