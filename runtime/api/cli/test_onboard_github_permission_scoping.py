"""Owner-scoped GitHub App permission and endpoint onboarding coverage."""

from __future__ import annotations

from yoke_cli.config import onboard_wizard


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
    monkeypatch.setattr(
        onboard_wizard.github_state,
        "user_access_token",
        lambda _result: "ghu_short_lived",
    )
    result = onboard_wizard.WizardResult(
        config_path="/tmp/config.json", env_name="prod", api_url="https://api.test",
        project_publish_to_github=True,
        project_publish_owner="target-org",
        project_publish_repo_name="widget",
    )

    request = result.build_publish_request()

    assert request is not None
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
