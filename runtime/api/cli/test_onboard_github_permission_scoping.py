"""Owner-scoped GitHub App permission and endpoint onboarding coverage."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_cli.config import onboard_wizard
from yoke_cli.config import onboard_wizard_project_github


def test_publish_administration_must_match_selected_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        onboard_wizard.machine_config,
        "github_config",
        lambda _path: {
            "api_url": "https://ghe.example/api/v3",
            "web_url": "https://ghe.example",
            "installations": [
                {
                    "account_login": "personal-owner",
                    "permissions": {"administration": "write"},
                },
                {
                    "account_login": "target-org",
                    "permissions": {"administration": "read"},
                },
            ],
        },
    )
    result = onboard_wizard.WizardResult(
        config_path="/tmp/config.json", env_name="prod", api_url="https://api.test",
        machine_github_choice="connect",
        machine_github_verification={"ok": True, "ready": True},
        project_publish_to_github=True,
        project_publish_owner="target-org",
        project_publish_repo_name="widget",
    )

    request = result.build_publish_request()

    assert request is not None
    assert request.token is None
    assert request.use_machine_github is True
    assert request.administration_allowed is False
    assert request.web_url == "https://ghe.example"


def test_suspended_owner_installation_cannot_enable_creation(monkeypatch) -> None:
    monkeypatch.setattr(
        onboard_wizard.machine_config,
        "github_config",
        lambda _path: {
            "installations": [{
                "account_login": "target-org",
                "suspended": True,
                "permissions": {"administration": "write"},
            }],
        },
    )
    result = onboard_wizard.WizardResult(
        config_path="/tmp/config.json", env_name="prod", api_url="https://api.test",
        project_publish_owner="target-org",
    )

    assert onboard_wizard.github_state.administration_allowed(result) is False


def test_project_access_check_uses_wizard_selected_service(monkeypatch) -> None:
    captured: dict = {}

    class _Flow(onboard_wizard_project_github.ProjectGithubAccessFlow):
        result = SimpleNamespace(
            config_path="/tmp/config.json",
            api_url="https://stage.yoke.example",
        )

        def _run_checking(self, **kwargs):
            captured.update(kwargs)

    status_kwargs: dict = {}
    monkeypatch.setattr(
        onboard_wizard_project_github.github_machine,
        "status",
        lambda **kwargs: status_kwargs.update(kwargs) or {"ok": True},
    )

    _Flow()._on_project_github_access("refresh")
    captured["work"]()

    assert status_kwargs["service_api_url"] == "https://stage.yoke.example"
