"""Machine preparation precedes the TUI and never withholds its choices."""

from pathlib import Path
from types import SimpleNamespace

from yoke_cli.commands.adapters import onboard_interactive
from yoke_cli.config import (
    machine_config,
    onboard_machine_setup as setup,
    onboard_report,
)


def test_directories_are_convergent_and_repair_deleted_state(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    calls = []
    original = setup.writer.set_runtime_paths

    def write(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(setup.writer, "set_runtime_paths", write)
    setup.setup_directories(config)
    assert Path(machine_config.temp_root(config)).is_dir()
    assert machine_config.cache_dir(config).is_dir()
    setup.setup_directories(config)
    assert len(calls) == 1
    machine_config.cache_dir(config).rmdir()
    setup.setup_directories(config)
    assert len(calls) == 2
    assert all(setup.directory_readiness(config).values())


def test_preparation_continues_after_a_failure(tmp_path, monkeypatch, capsys):
    calls = []

    def fail(_path):
        raise OSError("scratch_permissions_denied")

    monkeypatch.setattr(setup, "setup_directories", fail)
    monkeypatch.setattr(setup, "setup_browser", lambda *a: calls.append("browser"))
    setup.prepare(tmp_path / "config.json")
    assert calls == ["browser"]
    output = capsys.readouterr().err
    assert "scratch_permissions_denied" in output
    assert "Continuing to the wizard; Apply will retry" in output


def test_wizard_runs_after_preparation_even_when_browser_setup_fails(
    tmp_path, monkeypatch
):
    events = []
    monkeypatch.setattr(
        setup, "setup_directories", lambda path: events.append("directories")
    )

    def fail(*args):
        events.append("browser")
        raise RuntimeError("browser_install_failed: network unavailable")

    monkeypatch.setattr(setup, "setup_browser", fail)
    monkeypatch.setattr(
        onboard_interactive, "finish_pending_source_install", lambda _: None
    )

    def wizard(defaults, **kwargs):
        events.append("wizard")
        return SimpleNamespace(error=None, cancelled=False, exit_code=0)

    monkeypatch.setattr(onboard_interactive.onboard_wizard, "run_wizard", wizard)
    parsed = SimpleNamespace(
        config_path=str(tmp_path / "cfg.json"),
        api_url=None,
        token=None,
        token_file=None,
        quick=False,
        advanced=False,
        project_mode=None,
        project_checkout=None,
        apply=False,
        post_install=False,
    )
    assert (
        onboard_interactive.run_wizard(
            parsed,
            "",
            "quick",
            None,
            apply_with_report=lambda *a: {},
            print_failure=lambda _: None,
        )
        == 0
    )
    assert events == ["directories", "browser", "wizard"]


def test_review_excludes_deterministic_setup_and_keeps_choice_dependent_steps(tmp_path):
    plan = onboard_report.build_plan(
        tmp_path / "config.json",
        "chosen",
        "https://example.invalid",
        {},
        {},
        "quick",
        project_mode="machine-only",
        project_inputs={},
        machine_github={"choice": "connect"},
    )
    actions = [step["action"] for step in plan["steps"]]
    assert "create-runtime-dir" not in actions
    assert "browser-setup" not in actions
    assert "harness-unattended-posture" in actions
    assert "machine-github-connection" in actions
    assert "register-machine" in actions
    assert any(action.startswith("install-session-relay") for action in actions)


def test_onboard_wsl_reuses_setup_and_reports_restart(monkeypatch):
    from yoke_harness import wsl, wsl_systemd

    monkeypatch.setattr(wsl, "is_wsl", lambda: True)
    calls = []
    monkeypatch.setattr(
        wsl_systemd, "setup", lambda **kw: calls.append(kw) or "restart_required"
    )
    report = {}
    setup.setup_wsl(report)
    assert len(calls) == 1
    assert report["wsl_setup"]["status"] == "restart_required"


def test_onboard_wsl_failure_is_not_reported_ready(monkeypatch):
    import pytest
    from yoke_harness import wsl, wsl_systemd

    monkeypatch.setattr(wsl, "is_wsl", lambda: True)

    def fail(**kw):
        raise RuntimeError("wsl_lifetime_version_unsupported: run wsl --update")

    monkeypatch.setattr(wsl_systemd, "setup", fail)
    report = {}
    with pytest.raises(RuntimeError, match="wsl_lifetime_version_unsupported"):
        setup.setup_wsl(report)
    assert "wsl_setup" not in report


def test_prepare_runs_wsl_check_on_wsl_only(tmp_path, monkeypatch):
    from yoke_harness import wsl

    monkeypatch.setattr(setup, "setup_directories", lambda *args: None)
    monkeypatch.setattr(setup, "setup_browser", lambda *args: None)
    calls = []
    monkeypatch.setattr(setup, "setup_wsl", lambda report: calls.append("wsl"))
    monkeypatch.setattr(wsl, "is_wsl", lambda: False)
    setup.prepare(tmp_path / "config.json")
    assert not calls
    monkeypatch.setattr(wsl, "is_wsl", lambda: True)
    setup.prepare(tmp_path / "config.json")
    assert calls == ["wsl"]


def test_apply_rechecks_wsl_before_relay(monkeypatch, tmp_path):
    from yoke_cli.config import onboard_apply_runtime as runtime

    events = []
    monkeypatch.setattr(setup, "setup_directories", lambda *a, **kw: None)
    monkeypatch.setattr(setup, "setup_wsl", lambda *a, **kw: events.append("wsl"))
    monkeypatch.setattr(setup, "setup_browser", lambda *a, **kw: None)
    monkeypatch.setattr(
        runtime.onboard_session_relay, "apply", lambda *a, **kw: events.append("relay")
    )
    monkeypatch.setattr(
        runtime.onboard_machine_registry, "apply", lambda *a, **kw: None
    )
    runtime.apply(
        config_path=tmp_path / "config.json",
        reuse={},
        harness_posture=False,
        progress=None,
        report={},
        local_destination=False,
        environment="prod",
    )
    assert events == ["wsl", "relay"]
