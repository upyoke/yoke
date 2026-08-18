"""Release-channel coherence tests for materialized QA cases."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain.installer_campaign_plan_common import (
    CHOOSE_PRODUCTION_KEYS,
    CHOOSE_STAGE_KEYS,
)
from yoke_core.domain.machine_qa_method_contracts import (
    validate_machine_method_config,
)
from yoke_core.domain.machine_qa_fixture_validation import (
    validate_setup_operations,
)
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    _yoke_endpoints,
    require_case_target,
)


def _target(environment: str) -> dict:
    endpoints = _yoke_endpoints(environment, "upyoke")
    return {
        "environment": {"name": environment},
        "endpoints": endpoints,
    }


@pytest.mark.parametrize(
    "environment, expected_channel, expected_destination_keys",
    [
        ("stage", "latest", CHOOSE_STAGE_KEYS),
        ("prod", "stable", CHOOSE_PRODUCTION_KEYS),
    ],
)
def test_hosted_environment_projects_its_release_channel(
    environment,
    expected_channel,
    expected_destination_keys,
) -> None:
    target = _target(environment)
    endpoints = target["endpoints"]

    cases = installer_campaign_cases_for_target(target)
    rendered = json.dumps(cases)

    assert endpoints["release_channel"] == expected_channel
    assert f"YOKE_CHANNEL={expected_channel}" in rendered
    assert f'"channel": "{expected_channel}"' in rendered
    destination_actions = [
        action
        for case in cases
        for config in case.get("method_config", {})
        .get(
            "baseline_configs",
            {},
        )
        .values()
        for action in config.get("actions", [])
        if action.get("step") == "destination-picker"
    ]
    assert destination_actions
    assert {action["target_environment"] for action in destination_actions} == {
        target["environment"]["name"]
    }
    assert {tuple(action["keys"]) for action in destination_actions} == {
        expected_destination_keys
    }


@pytest.mark.parametrize("environment", ["stage", "prod"])
def test_projected_installer_cases_remain_executable(environment: str) -> None:
    cases = installer_campaign_cases_for_target(_target(environment))
    hosted = next(case for case in cases if case["case_key"] == "cold-start-hosted")
    for config in hosted["method_config"]["baseline_configs"].values():
        actions = {action["step"]: action for action in config["actions"]}
        assert actions["project-mode"]["ready_timeout_seconds"] == 45
        assert actions["project-mode-machine-only"]["keys"] == [
            "Down",
            "Down",
            "Down",
            "Down",
            "Enter",
        ]
        assert actions["review"]["ready_timeout_seconds"] == 45
    for case in cases:
        for baseline in case.get("host_baselines") or [None]:
            config = validate_machine_method_config(
                case["method_id"],
                case["method_config"],
                entry_surface=case.get("entry_surface"),
                required_completion=case.get("required_completion"),
                host_baseline=baseline,
            )
            if "baseline_configs" not in config:
                validate_setup_operations(config.get("setup_operations", []))


@pytest.mark.parametrize(
    "case",
    [
        {"method_config": {"setup_operations": [{"channel": "latest"}]}},
        {"entry_surface": "YOKE_CHANNEL=latest /bin/sh"},
    ],
)
def test_case_guard_rejects_opposite_release_channel(case) -> None:
    target = _target("prod")
    with pytest.raises(QaExecutionTargetError, match="release channel"):
        require_case_target(case, target)


@pytest.mark.parametrize(
    "binding",
    [None, "another-environment"],
)
def test_case_guard_requires_exact_interactive_environment_binding(binding) -> None:
    action = {"step": "destination-picker", "keys": ["Down", "Enter"]}
    if binding is not None:
        action["target_environment"] = binding
    case = {"method_config": {"actions": [action]}}

    with pytest.raises(QaExecutionTargetError, match="destination binding"):
        require_case_target(case, _target("stage"))


def test_external_distribution_binding_is_generic_and_exact() -> None:
    target = {
        "environment": {"name": "blue"},
        "endpoints": {
            "installer_base_url": "https://downloads.example.net/yoke",
            "release_channel": "customer-canary.7",
        },
    }
    operation = {
        "id": "installer.current-release-prepare",
        "parameters": {
            "base_url": target["endpoints"]["installer_base_url"],
            "channel": target["endpoints"]["release_channel"],
            "evidence_name": "external-release",
            "no_onboard": True,
            "remove_existing_launcher": True,
        },
    }
    case = {"method_config": {"setup_operations": [operation]}}

    require_case_target(case, target)
    validate_setup_operations([operation])

    operation["parameters"]["channel"] = "another-channel"
    with pytest.raises(QaExecutionTargetError, match="release channel"):
        require_case_target(case, target)


def test_self_hosted_distribution_binding_accepts_local_http_target() -> None:
    target = {
        "environment": {"name": "local"},
        "endpoints": {
            "installer_base_url": "http://127.0.0.1:8765/distribution",
            "release_channel": "development",
        },
    }
    operation = {
        "id": "installer.current-release-prepare",
        "parameters": {
            "base_url": target["endpoints"]["installer_base_url"],
            "channel": target["endpoints"]["release_channel"],
            "evidence_name": "local-release",
            "no_onboard": True,
            "remove_existing_launcher": True,
        },
    }

    require_case_target(
        {"method_config": {"setup_operations": [operation]}},
        target,
    )
    validate_setup_operations([operation])
