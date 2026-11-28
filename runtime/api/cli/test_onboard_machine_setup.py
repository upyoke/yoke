"""Machine preparation precedes the TUI and never withholds its choices."""

from pathlib import Path
from types import SimpleNamespace

from runtime.api.fixtures.machine_config_test import select_machine_config_file

import pytest

from yoke_cli.commands.adapters import onboard_apply, onboard_interactive
from yoke_cli.config import onboard_machine_setup as setup, onboard_report


def test_directories_are_convergent_and_repair_deleted_state(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    select_machine_config_file(monkeypatch, config)
    setup.setup_directories(config)
    assert all(setup.directory_readiness(config).values())
    setup.setup_directories(config)
    (config.parent / "cache").rmdir()
    assert not setup.directory_readiness(config)["cache_dir"]
    setup.setup_directories(config)
    assert all(setup.directory_readiness(config).values())
    assert not config.exists()


def test_directory_preparation_preserves_existing_config(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    select_machine_config_file(monkeypatch, config)
    payload = b'{"temp_root":"custom-tmp","cache_dir":"custom-cache","machine_id":"8bea37d8-e2d5-4e4d-96c4-cfc53d9dbe5f"}'
    config.write_bytes(payload)

    setup.setup_directories(config)

    assert config.read_bytes() == payload
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
        onboard_interactive, "require_foreground_terminal", lambda: None
    )
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
        project_slug=None,
        project_clone_outcome=None,
        apply=False,
        post_install=False,
        machine_github=None,
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


def test_interactive_posture_is_in_preview_and_apply(tmp_path, monkeypatch):
    from yoke_cli.commands.adapters import onboard as adapter
    from yoke_cli.config.onboard_wizard_app import OnboardWizardApp

    monkeypatch.setattr(setup, "prepare", lambda *_: None)
    monkeypatch.setattr(
        onboard_interactive, "require_foreground_terminal", lambda: None
    )
    monkeypatch.setattr(
        onboard_interactive.onboard_wizard, "is_interactive", lambda *_: True
    )
    monkeypatch.setattr(
        onboard_interactive, "finish_pending_source_install", lambda _: None
    )
    monkeypatch.setattr(
        OnboardWizardApp, "_hydrate_stored_credentials", lambda *_: None
    )
    plans = []

    def assemble(kwargs, **_):
        plan = onboard_report.build_plan(
            Path(kwargs["config_path"]),
            kwargs["env_name"],
            kwargs["api_url"],
            {},
            {},
            kwargs["mode"],
            project_mode="machine-only",
            project_inputs={},
            machine_github={"choice": kwargs["machine_github_choice"]},
        )
        plans.append((kwargs["apply"], [step["action"] for step in plan["steps"]]))
        return {"plan": plan}

    def wizard(defaults, *, apply_report):
        app = OnboardWizardApp(defaults=defaults, apply_report=apply_report)
        assemble(app.result.build_report_kwargs(apply=False, check_identity=False))
        apply_report(app.result.build_report_kwargs(apply=True, check_identity=False))
        return SimpleNamespace(error=None, cancelled=False, exit_code=0)

    monkeypatch.setattr(onboard_interactive.onboard_wizard, "run_wizard", wizard)
    monkeypatch.setattr(onboard_apply, "apply_with_durable_report", assemble)
    arguments = [
        "--connect",
        "https://app.upyoke.com",
        "--config",
        str(tmp_path / "cfg.json"),
    ]
    assert adapter.onboard(arguments) == 0
    assert [applied for applied, _ in plans] == [False, True]
    assert all(
        "harness-unattended-posture" in actions for _, actions in plans
    )


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
    assert "install-yoke-global-skill" in actions
    relay_action = next(
        action for action in actions if action.startswith("install-session-relay")
    )
    assert actions.index("register-machine") < actions.index(relay_action)


def test_onboard_wsl_reuses_setup_and_reports_restart(monkeypatch):
    from yoke_contracts import wsl
    from yoke_harness import wsl_systemd

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
    from yoke_contracts import wsl
    from yoke_harness import wsl_systemd

    monkeypatch.setattr(wsl, "is_wsl", lambda: True)

    def fail(**kw):
        raise RuntimeError("wsl_lifetime_config_invalid: repair config")

    monkeypatch.setattr(wsl_systemd, "setup", fail)
    report = {}
    with pytest.raises(RuntimeError, match="wsl_lifetime_config_invalid"):
        setup.setup_wsl(report)
    assert "wsl_setup" not in report


def test_prepare_never_writes_wsl_configuration(tmp_path, monkeypatch):
    from yoke_contracts import wsl

    monkeypatch.setattr(setup, "setup_directories", lambda *args: None)
    monkeypatch.setattr(setup, "setup_browser", lambda *args: None)
    calls = []
    monkeypatch.setattr(setup, "setup_wsl", lambda report: calls.append("wsl"))
    monkeypatch.setattr(wsl, "is_wsl", lambda: False)
    setup.prepare(tmp_path / "config.json")
    assert not calls
    monkeypatch.setattr(wsl, "is_wsl", lambda: True)
    setup.prepare(tmp_path / "config.json")
    assert not calls


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
        progress=None,
        report={},
        local_destination=False,
        environment="prod",
    )
    assert events == ["wsl", "relay"]


@pytest.mark.parametrize("reused", [False, True], ids=["install", "reuse"])
def test_apply_registers_machine_before_relay(monkeypatch, tmp_path, reused):
    from yoke_cli.config import onboard_apply_runtime as runtime

    events = []
    relay = runtime.onboard_session_relay
    monkeypatch.setattr(setup, "setup_directories", lambda *a, **kw: None)
    monkeypatch.setattr(setup, "setup_wsl", lambda *a, **kw: events.append("wsl"))
    monkeypatch.setattr(setup, "setup_browser", lambda *a, **kw: None)
    monkeypatch.setattr(
        runtime.onboard_machine_registry,
        "register_this_machine",
        lambda config_path: events.append("register") or {"registered": True},
    )

    def install_relay(**kwargs):
        events.append("relay")
        return relay.RelayInstallOutcome(installed=True, reused=reused, connected=True)

    monkeypatch.setattr(relay, "install", install_relay)
    report = {}
    runtime.apply(
        config_path=tmp_path / "config.json",
        reuse={},
        progress=None,
        report=report,
        local_destination=False,
        environment="prod",
    )
    assert events == ["wsl", "register", "relay"]
    assert report["session_relay"]["reused"] is reused


def test_apply_finishes_with_an_old_wsl_warning(monkeypatch, capsys):
    from yoke_contracts import wsl
    from yoke_harness import wsl_systemd, wsl_lifetime

    monkeypatch.setattr(wsl, "is_wsl", lambda: True)
    monkeypatch.setattr(wsl_systemd, "is_wsl", lambda: True)
    monkeypatch.setattr(wsl_systemd, "_setup_systemd", lambda **kw: "already_running")
    monkeypatch.setattr(wsl_lifetime, "_windows_command", lambda name: name)
    monkeypatch.setattr(wsl_lifetime, "_run", lambda command: "WSL version: 2.5.3.0")
    monkeypatch.setattr(
        wsl_lifetime, "_config_path", lambda: pytest.fail("unsupported version")
    )
    report = {}
    setup.setup_wsl(report)
    assert report["wsl_setup"]["status"] == "already_running"
    assert "Warning:" in capsys.readouterr().err
