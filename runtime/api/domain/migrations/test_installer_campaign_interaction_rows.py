from __future__ import annotations

from runtime.api.domain.migrations.installer_campaign_assertions import (
    action_signature,
    action_window,
    selection_keys,
    terminal_configs,
)
from yoke_cli.config import onboard_machine_github
from yoke_cli.config.onboard_destination_rows import (
    DESTINATION_ROWS,
    HOSTED_STAGE_ROW,
)
from yoke_cli.config.onboard_project_modes import PROJECT_MODE_MACHINE_ONLY
from yoke_cli.config.onboard_wizard_steps import MACHINE_GITHUB_ROWS, MODE_ROWS
from yoke_contracts.api_urls import (
    DISTRIBUTION_STAGE_URL,
    HOSTED_STAGE_PLATFORM_URL,
)
from yoke_core.domain.installer_campaign_current_text_cases import (
    CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
)


INSTALLER_CAMPAIGN_CASES = CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES


def test_user_facing_terminal_cases_use_the_native_terminal_app_mode() -> None:
    for case in INSTALLER_CAMPAIGN_CASES:
        if case["method_id"] not in {"terminal-check", "terminal-inspection"}:
            continue
        raw_config = case["method_config"]
        configs = raw_config.get("baseline_configs", {}).values()
        if not configs:
            configs = (raw_config,)
        for config in configs:
            expected = (
                "ssh-command" if case["case_key"] == "path-repair" else "terminal"
            )
            assert config["execution_mode"] == expected


def test_terminal_cases_use_current_stage_and_browser_approval_surfaces() -> None:
    cases = {case["case_key"]: case for case in INSTALLER_CAMPAIGN_CASES}

    cold = cases["cold-start-hosted"]
    assert f"{DISTRIBUTION_STAGE_URL}/install" in cold["entry_surface"]
    assert cold["host_baselines"] == [
        "fresh-host",
        "shell-preconfigured",
    ]
    cold_configs = cold["method_config"]["baseline_configs"]
    assert set(cold_configs) == {"fresh-host", "shell-preconfigured"}
    assert all(
        "Sign in and choose an organization." in config["expected_text"]
        and "Setup complete." in config["expected_text"]
        and "Next: make it execution-ready." in config["expected_text"]
        and "terminal_exit_code:0" in config["post_checks"]
        for config in cold_configs.values()
    )
    assert (
        cold_configs["fresh-host"]["expected_text"]
        != cold_configs["shell-preconfigured"]["expected_text"]
    )
    for config in cold_configs.values():
        actions = {action["step"]: action for action in config["actions"]}
        assert tuple(actions["destination-picker"]["keys"]) == selection_keys(
            DESTINATION_ROWS,
            HOSTED_STAGE_ROW,
        )
        assert actions["browser-approval"].get("keys", []) == []
        assert actions["review"].get("keys", []) == []

    hosted = cases["hosted-connect"]
    assert HOSTED_STAGE_PLATFORM_URL in hosted["entry_surface"]
    assert (
        "Sign in and choose an organization."
        in (hosted["method_config"]["expected_text"])
    )
    assert hosted["required_completion"] == "hosted-connected"

    path = cases["path-repair"]
    assert path["method_config"]["execution_mode"] == "ssh-command"
    assert '"verified": true' in path["method_config"]["expected_text"]
    assert '"ssh_verified": true' in path["method_config"]["expected_text"]

    handoff = cases["apply-handoff"]
    assert f"{DISTRIBUTION_STAGE_URL}/install" in handoff["entry_surface"]
    assert "YOKE_ONBOARD_DESTINATION=local" in handoff["entry_surface"]
    assert HOSTED_STAGE_PLATFORM_URL not in handoff["entry_surface"]
    assert (
        "Your Yoke lives on this machine."
        in (handoff["method_config"]["expected_text"])
    )
    assert "Report:" in handoff["method_config"]["expected_text"]
    assert (
        "Next: make it execution-ready." in (handoff["method_config"]["expected_text"])
    )
    assert "One-time code:" not in handoff["method_config"]["expected_text"]
    assert "terminal_exit_code:0" in handoff["method_config"]["post_checks"]

    setup_ids = {
        operation["id"]
        for case in INSTALLER_CAMPAIGN_CASES
        for config in terminal_configs(case)
        for operation in config.get("setup_operations", [])
    }
    assert setup_ids == {
        "installer.current-release-prepare",
        "machine.path-prepare",
        "machine.yoke-auth-clear",
    }
    assert all(
        "--token" not in str(case["entry_surface"] or "")
        for case in INSTALLER_CAMPAIGN_CASES
    )


def test_hosted_actions_pin_send_before_capture_transitions() -> None:
    cases = {case["case_key"]: case for case in INSTALLER_CAMPAIGN_CASES}
    backlog_keys = selection_keys(
        MACHINE_GITHUB_ROWS,
        onboard_machine_github.CHOICE_SKIP,
    )
    machine_only_keys = selection_keys(MODE_ROWS, PROJECT_MODE_MACHINE_ONLY)
    approval_to_review = [
        ("browser-approval", ()),
        ("operator-browser-approval", ("Enter",)),
        ("hosted-connected", ()),
        ("continue-hosted-connected", ("Enter",)),
        ("machine-github", ()),
        ("machine-github-backlog", backlog_keys),
        ("project-mode", ()),
        ("project-mode-machine-only", machine_only_keys),
        ("review", ()),
    ]
    for config in cases["cold-start-hosted"]["method_config"][
        "baseline_configs"
    ].values():
        assert (
            action_window(
                config,
                first="browser-approval",
                last="review",
            )
            == approval_to_review
        )
        actions = {action["step"]: action for action in config["actions"]}
        approval = actions["operator-browser-approval"]
        assert approval["operator_gate"] == "machine_browser_approval"
        assert approval["completion_text"] == ["Yoke token connected."]
        assert approval["gate_timeout_seconds"] == 600
        assert "wait_seconds" not in approval
        assert actions["hosted-connected"]["ready_text"] == ["Yoke token connected."]
        assert actions["machine-github-backlog"]["ready_text"] == ["Connect GitHub?"]
        assert actions["project-mode"]["ready_timeout_seconds"] == 45
        assert actions["project-mode-machine-only"]["ready_timeout_seconds"] == 45
        assert actions["review"]["ready_text"] == [
            "Review what Yoke will save.",
            "Apply",
        ]
        assert actions["review"]["ready_timeout_seconds"] == 45

    hosted_config = cases["hosted-connect"]["method_config"]
    assert action_signature(hosted_config) == [
        ("path-ready", ()),
        ("continue-path", ("Enter",)),
        ("browser-approval", ()),
        ("operator-browser-approval", ("Enter",)),
        ("hosted-connected", ()),
    ]
    hosted_actions = {action["step"]: action for action in hosted_config["actions"]}
    assert (
        hosted_actions["operator-browser-approval"]["operator_gate"]
        == "machine_browser_approval"
    )
    assert "wait_seconds" not in hosted_actions["operator-browser-approval"]
    assert hosted_actions["path-ready"]["ready_text"] == [
        "Yoke is already on your PATH.",
    ]
    assert hosted_actions["hosted-connected"]["ready_text"] == ["Yoke token connected."]

    connect_wait_config = cases["connect-wait"]["method_config"]
    assert action_signature(connect_wait_config) == [
        ("path-ready", ()),
        ("continue-path", ("Enter",)),
        ("connect-wait", ()),
    ]
    connect_wait_actions = {
        action["step"]: action for action in connect_wait_config["actions"]
    }
    assert connect_wait_actions["path-ready"]["ready_text"] == [
        "Yoke is already on your PATH.",
    ]

    review_config = cases["review-frame"]["method_config"]
    assert action_signature(review_config) == [
        ("path-ready", ()),
        ("continue-path", ("Enter",)),
        ("browser-approval", ()),
        ("operator-browser-approval", ("Enter",)),
        ("hosted-connected", ()),
        ("continue-hosted-connected", ("Enter",)),
        ("machine-github", ()),
        ("machine-github-backlog", backlog_keys),
        ("review-frame", ()),
    ]
    assert all(
        step not in {"project-mode", "project-mode-machine-only"}
        for step, _keys in action_signature(review_config)
    )
    review_actions = {action["step"]: action for action in review_config["actions"]}
    assert review_actions["path-ready"]["ready_text"] == [
        "Yoke is already on your PATH.",
    ]
    assert review_actions["review-frame"]["ready_text"] == [
        "Review what Yoke will save.",
        "Apply",
    ]


def test_inspection_and_machine_state_cases_are_semantic() -> None:
    cases = {case["case_key"]: case for case in INSTALLER_CAMPAIGN_CASES}

    assert cases["welcome-frame"]["host_baselines"] == []
    assert cases["welcome-frame"]["method_config"]["setup_operations"] == []
    assert cases["welcome-frame"]["method_config"]["actions"] == [
        {
            "step": "welcome-frame",
            "wait_seconds": 3,
        }
    ]
    assert cases["welcome-frame"]["method_config"]["capture_checkpoints"] == [
        "welcome-frame"
    ]
    assert (
        "Yoke's only prerequisite"
        in (cases["welcome-frame"]["method_config"]["expected_text"])
    )
    welcome_entry = cases["welcome-frame"]["entry_surface"]
    assert "HOME=/var/empty" in welcome_entry
    assert "XDG_BIN_HOME=/var/empty/.local/bin" in welcome_entry
    assert "PATH=/usr/bin:/bin:/usr/sbin:/sbin" in welcome_entry
    assert cases["connect-wait"]["method_config"]["capture_checkpoints"] == [
        "connect-wait"
    ]
    assert cases["review-frame"]["method_config"]["capture_checkpoints"] == [
        "browser-approval",
        "review-frame",
    ]
    assert (
        "Review what Yoke will save."
        in (cases["review-frame"]["method_config"]["expected_text"])
    )
    review_actions = {
        action["step"]: action
        for action in cases["review-frame"]["method_config"]["actions"]
    }
    assert review_actions["machine-github"].get("keys", []) == []
    assert review_actions["machine-github-backlog"]["keys"] == ["Down", "Enter"]
    assert review_actions["review-frame"].get("keys", []) == []

    path_configs = cases["path-on-shell"]["method_config"]["baseline_configs"]
    assert set(path_configs) == {"fresh-host", "shell-preconfigured"}
    assert all(len(config["assertions"]) == 2 for config in path_configs.values())
    assert (
        "! command -v yoke" in (path_configs["fresh-host"]["assertions"][0]["argv"][-1])
    )
    assert (
        "yoke --version"
        in (path_configs["shell-preconfigured"]["assertions"][0]["argv"][-1])
    )

    token_command = cases["token-perms"]["method_config"]["assertions"][0]["argv"][-1]
    assert "*.token(N)" in token_command
    assert "'%Lp'" in token_command
    assert "600" in token_command
    assert "read" not in token_command

    universe_assertions = cases["universe-born"]["method_config"]["assertions"]
    assert "yoke local-postgres status --json" in universe_assertions[0]["argv"][-1]
    assert "local.dsn" in universe_assertions[1]["argv"][-1]


def test_product_rows_and_action_boundaries_select_the_intended_targets() -> None:
    assert DESTINATION_ROWS[3].value == HOSTED_STAGE_ROW
    assert MACHINE_GITHUB_ROWS[1].value == onboard_machine_github.CHOICE_SKIP
    assert MODE_ROWS[4].value == PROJECT_MODE_MACHINE_ONLY

    cases = {case["case_key"]: case for case in INSTALLER_CAMPAIGN_CASES}
    handoff_actions = {
        action["step"]: action
        for action in cases["apply-handoff"]["method_config"]["actions"]
    }
    assert handoff_actions["machine-github"]["keys"] == ["Down", "Enter"]
    assert handoff_actions["project-mode"]["keys"] == [
        "Down",
        "Down",
        "Down",
        "Down",
        "Enter",
    ]
    assert handoff_actions["review"].get("keys", []) == []
