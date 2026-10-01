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
