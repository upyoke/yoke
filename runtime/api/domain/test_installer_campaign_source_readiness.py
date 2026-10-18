"""Every installer campaign step that sends keys names the prompt it answers."""

from __future__ import annotations

import pytest

from runtime.api.domain.installer_campaign_test_support import terminal_configs
from yoke_contracts.api_urls import DISTRIBUTION_STAGE_URL, HOSTED_STAGE_PLATFORM_URL
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain.machine_qa_action_readiness_contract import (
    require_keyed_ready_text,
)
from yoke_core.domain.machine_qa_recipe_contracts import validate_terminal_recipe


_TARGETS = {
    "stage": {
        "environment": {"name": "stage"},
        "endpoints": {
            "app_url": HOSTED_STAGE_PLATFORM_URL,
            "installer_base_url": DISTRIBUTION_STAGE_URL,
            "release_channel": "latest",
        },
        "role": {"production": False},
    },
    "prod": {
        "environment": {"name": "prod"},
        "endpoints": {
            "app_url": "https://app.upyoke.com",
            "installer_base_url": "https://api.upyoke.com",
            "release_channel": "stable",
        },
        "role": {"production": True},
    },
}


def _recipes(target_name: str):
    cases = installer_campaign_cases_for_target(
        _TARGETS[target_name],
        primary_machine="primary-test",
        joining_machine="joining-test",
    )
    for case in cases:
        if not str(case["method_id"]).startswith("terminal-"):
            continue
        for config in terminal_configs(case):
            if "actions" in config:
                yield case, config


@pytest.mark.parametrize("target_name", sorted(_TARGETS))
def test_every_source_keyed_step_declares_ready_text(target_name: str) -> None:
    unready = []
    for case, config in _recipes(target_name):
        for action in config["actions"]:
            try:
                require_keyed_ready_text(action)
            except ValueError:
                unready.append(f"{case['case_key']}:{action['step']}")
    assert unready == []


@pytest.mark.parametrize("target_name", sorted(_TARGETS))
def test_every_source_recipe_passes_the_execution_contract(target_name: str) -> None:
    for case, config in _recipes(target_name):
        recipe = {key: value for key, value in config.items() if key != "machine"}
        validate_terminal_recipe(
            recipe,
            required_completion=case["required_completion"]
            or recipe["actions"][-1]["step"],
        )
