"""Local campaign birth supplies the name required by the live setup prompt."""

from yoke_cli.config import onboard_wizard_admin_name
from yoke_contracts.first_admin_name import validate_admin_name
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain.installer_campaign_plan_common import (
    APPLY_SUCCESS_TEXT,
    PARENT_HANDOFF_TEXT,
    REVIEW_TEXT,
)


def _local_birth_config():
    cases = installer_campaign_cases_for_target(
        {
            "environment": {"name": "prod"},
            "endpoints": {
                "app_url": "https://app.example.test",
                "installer_base_url": "https://api.example.test",
                "release_channel": "stable",
            },
            "role": {"production": True},
        },
        primary_machine="primary-test",
        joining_machine="joining-test",
    )
    return next(
        case["method_config"] for case in cases if case["case_key"] == "apply-handoff"
    )


def test_local_birth_action_satisfies_the_live_admin_name_prompt():
    config = _local_birth_config()
    actions = config["actions"]
    name_index = next(
        index
        for index, action in enumerate(actions)
        if action["step"] == "local-admin-name"
    )
    name_action = actions[name_index]
    assert actions[name_index - 1]["step"] == "continue-local-universe"
    assert actions[name_index + 1]["step"] == "machine-github"
    assert name_action["ready_text"] == [
        onboard_wizard_admin_name.TITLE,
        onboard_wizard_admin_name.SUBTITLE,
    ]
    name, enter = name_action["keys"]
    assert enter == "Enter"
    assert validate_admin_name(name) == name

    class Shell:
        def _goto_input(self, key, step, title, subtitle, **kwargs):
            assert title in name_action["ready_text"]
            assert subtitle in name_action["ready_text"]
            assert kwargs["allow_placeholder"] is False
            assert kwargs["validate"](name) is None
            assert kwargs["validate"]("") is not None
            kwargs["on_done"](name)

    accepted = []
    onboard_wizard_admin_name.prompt(
        Shell(), "local", current=None, on_done=accepted.append
    )
    assert accepted == [name]


def test_local_name_entry_preserves_apply_report_exit_and_parent_handoff():
    config = _local_birth_config()
    assert all(
        text in config["expected_text"]
        for text in (
            *REVIEW_TEXT,
            *APPLY_SUCCESS_TEXT,
            *PARENT_HANDOFF_TEXT,
        )
    )
    assert config["expected_return_codes"] == [0]
    assert "terminal_exit_code:0" in config["post_checks"]
    assert "no_text:Match code:" in config["post_checks"]
    assert "no_text:Paste your Yoke API token." in config["post_checks"]
    assert config["actions"][-1]["step"] == "complete-onboarding"
