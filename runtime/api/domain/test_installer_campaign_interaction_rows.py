from __future__ import annotations

from runtime.api.domain.installer_campaign_test_support import (
    terminal_configs,
)
from yoke_cli.config import onboard_machine_github
from yoke_cli.config.onboard_destination_rows import DESTINATION_ROWS
from yoke_cli.config.onboard_destinations import DESTINATION_HOSTED
from yoke_cli.config.onboard_project_modes import PROJECT_MODE_MACHINE_ONLY
from yoke_cli.config.onboard_wizard_steps import MACHINE_GITHUB_ROWS, MODE_ROWS
from yoke_contracts.api_urls import (
    DISTRIBUTION_STAGE_URL,
    HOSTED_STAGE_PLATFORM_URL,
)
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)


INSTALLER_CAMPAIGN_CASES = installer_campaign_cases_for_target(
    {
        "environment": {"name": "stage"},
        "endpoints": {
            "app_url": HOSTED_STAGE_PLATFORM_URL,
            "installer_base_url": DISTRIBUTION_STAGE_URL,
            "release_channel": "latest",
        },
        "role": {"production": False},
    },
    primary_machine="primary-test",
    joining_machine="joining-test",
)


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
                "ssh-command"
                if case["case_key"].startswith("install-health-")
                or case["case_key"].endswith("-prepare")
                or case["case_key"]
                in {
                    "path-repair",
                    "stale-reinstall",
                    "uninstall",
                    "late-harness-discovery",
                    "local-refusal-agent",
                }
                else "terminal"
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
    assert cold["method_id"] == "exploratory-mission"
    for text in ("Sign in and choose an organization.", "Setup complete.",
                 "Next: bring your existing work into Yoke.", "exit code 0"):
        assert text in cold["expected_outcome"]
    assert "YOKE_ONBOARD_DESTINATION=" in cold["entry_surface"]
    assert HOSTED_STAGE_PLATFORM_URL in cold["entry_surface"]
    assert "hosted-connect" not in cases

    path = cases["path-repair"]
    assert path["method_config"]["execution_mode"] == "ssh-command"
    assert '"login_verified": true' in path["method_config"]["expected_text"]
    assert '"command": "yoke path fix --yes"' in path["method_config"]["expected_text"]

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
        "Next: bring your existing work into Yoke."
        in (handoff["method_config"]["expected_text"])
    )
    assert "Match code:" not in handoff["method_config"]["expected_text"]
    assert "terminal_exit_code:0" in handoff["method_config"]["post_checks"]

    setup_ids = {
        operation["id"]
        for case in INSTALLER_CAMPAIGN_CASES
        for config in terminal_configs(case)
        for operation in config.get("setup_operations", [])
    }
    assert setup_ids == {
        "fixture.machine-admission-prepare",
        "installer.current-release-prepare",
        "machine.path-prepare",
        "machine.yoke-auth-clear",
    }
    assert all(
        "--token" not in str(case["entry_surface"] or "")
        for case in INSTALLER_CAMPAIGN_CASES
    )


def test_obstacle_cases_are_missions_with_boundary_and_workaround_evidence():
    cases = {case["case_key"]: case for case in INSTALLER_CAMPAIGN_CASES}
    keys = {"welcome-frame", "cold-start-hosted", "connect-wait", "review-frame",
            "second-machine-join"}
    assert {case["case_key"] for case in cases.values()
            if case["method_id"] == "exploratory-mission"} == keys
    for key in keys:
        case = cases[key]
        assert case["method_config"]["executor"] == "informed_subagent"
        assert "actions" not in case["method_config"]
        assert "workaround" in case["instructions"]
        assert "evidence" in case["instructions"]
        assert "yoke machines approve" in case["instructions"]
        assert "2FA" in case["instructions"] and "payment" in case["instructions"]
        assert "Traceback" in case["expected_outcome"]


def test_inspection_and_machine_state_cases_are_semantic() -> None:
    cases = {case["case_key"]: case for case in INSTALLER_CAMPAIGN_CASES}

    assert cases["welcome-frame"]["host_baselines"] == []
    assert "Installing uv" in cases["welcome-frame"]["expected_outcome"]
    assert "Exit code 1" in cases["welcome-frame"]["expected_outcome"]
    welcome_entry = cases["welcome-frame"]["entry_surface"]
    assert "HOME=/var/empty" in welcome_entry
    assert "XDG_BIN_HOME=/var/empty/.local/bin" in welcome_entry
    assert "PATH=/usr/bin:/bin:/usr/sbin:/sbin" in welcome_entry
    assert "authorization still pending" in cases["connect-wait"]["expected_outcome"]
    assert "Match code:" in cases["connect-wait"]["expected_outcome"]
    assert "Review what Yoke will save." in cases["review-frame"]["expected_outcome"]
    assert "end before Apply" in cases["review-frame"]["expected_outcome"]
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

    assert "token-perms" not in cases
    assert "mode 700" in cases["cold-start-hosted"]["expected_outcome"]
    assert "mode 600" in cases["cold-start-hosted"]["expected_outcome"]
    universe_assertions = cases["universe-born"]["method_config"]["assertions"]
    assert "yoke local-postgres status --json" in universe_assertions[0]["argv"][-1]
    assert "local.dsn" in universe_assertions[1]["argv"][-1]


def test_product_rows_and_action_boundaries_select_the_intended_targets() -> None:
    assert [row.value for row in DESTINATION_ROWS].count(DESTINATION_HOSTED) == 1
    assert all("stage" not in row.label.casefold() for row in DESTINATION_ROWS)
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


def test_missions_keep_the_original_visible_text_checks():
    from yoke_core.domain.installer_campaign_current_text_cases import (
        CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
    )

    cases = {case["case_key"]: case for case in INSTALLER_CAMPAIGN_CASES}
    for source in CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES:
        if source["case_key"] not in {"cold-start-hosted", "welcome-frame",
                                      "connect-wait", "review-frame"}:
            continue
        mission = cases[source["case_key"]]
        for config in terminal_configs(source):
            for text in config["expected_text"]:
                assert text in mission["expected_outcome"]
