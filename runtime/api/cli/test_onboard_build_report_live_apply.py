from yoke_cli.commands.adapters import onboard
from yoke_cli.commands.adapters import (
    onboard_apply,
    onboard_build_report,
    onboard_interactive,
)
from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_wizard


def test_build_report_uses_current_apply(monkeypatch):
    marker = {"report": "current apply"}
    monkeypatch.setattr(onboard_config, "build_report", lambda **kwargs: {})
    monkeypatch.setattr(onboard_apply, "apply_with_durable_report", lambda _: marker)

    report = onboard_build_report.build_report(
        config_path=None,
        env_name="local",
        api_url="",
        token=None,
        token_file=None,
        token_source_kind="argument",
        mode="quick",
        apply=False,
        check_identity=False,
        machine_github_choice="skip",
        machine_github_api_url=None,
        project_mode="machine-only",
        project_remote_url=None,
        project_checkout=None,
        project_slug=None,
        project_name=None,
        project_org=None,
        project_github_repo=None,
        project_default_branch=None,
        project_default_branch_source=None,
        project_public_item_prefix=None,
        existing_project_id=None,
        project_github_adoption=None,
    )

    assert report is marker


def test_wizard_uses_current_apply(monkeypatch, tmp_path):
    marker = {"report": "current apply"}
    monkeypatch.setattr(onboard_config, "build_report", lambda **kwargs: {})
    monkeypatch.setattr(
        onboard_apply, "apply_with_durable_report", lambda kwargs, **options: marker
    )
    monkeypatch.setattr(
        onboard_interactive, "require_foreground_terminal", lambda: None
    )
    monkeypatch.setattr(
        onboard_interactive.onboard_machine_setup, "prepare", lambda _: None
    )

    def run_wizard(defaults, *, apply_report):
        assert apply_report({}) is marker
        return onboard_wizard.WizardRunResult(exit_code=0)

    monkeypatch.setattr(onboard_wizard, "run_wizard", run_wizard)
    parsed = onboard._parser().parse_args(["--config", str(tmp_path / "config.json")])

    assert onboard._run_wizard(parsed, "local", "quick", "local") == 0


def test_applying_flags_uses_current_source_installer(monkeypatch, tmp_path):
    config_path = str(tmp_path / "config.json")
    calls = []

    def finish_source_install(path, *, stream):
        calls.append(path)

    monkeypatch.setattr(onboard, "_build_report", lambda **kwargs: {"applied": True})
    monkeypatch.setattr(
        onboard_interactive, "finish_pending_source_install", finish_source_install
    )

    assert (
        onboard.onboard(
            ["--local", "--non-interactive", "--json", "--config", config_path, "--yes"]
        )
        == 0
    )
    assert calls == [config_path]
