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
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    _yoke_endpoints,
    require_case_target,
)


def _target(environment: str) -> dict:
    endpoints = _yoke_endpoints(environment, "upyoke")
    return {
        "environment": {
            "id": f"yoke-api-{environment}",
            "name": environment,
        },
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
    assert {action["target_environment_id"] for action in destination_actions} == {
        target["environment"]["id"]
    }
    assert {tuple(action["keys"]) for action in destination_actions} == {
        expected_destination_keys
    }


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
        action["target_environment_id"] = binding
    case = {"method_config": {"actions": [action]}}

    with pytest.raises(QaExecutionTargetError, match="destination binding"):
        require_case_target(case, _target("stage"))
