"""Project the installer campaign onto one QA execution target."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from yoke_contracts.api_urls import (
    DISTRIBUTION_STAGE_URL,
    HOSTED_STAGE_PLATFORM_URL,
)
from yoke_core.domain.installer_campaign_current_text_cases import (
    CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
)
from yoke_core.domain.installer_campaign_plan_common import (
    CHOOSE_PRODUCTION_KEYS,
    CHOOSE_STAGE_KEYS,
)
from yoke_core.domain.qa_execution_environment_target import require_case_target


def _replace_text(value: str, target: Mapping[str, Any]) -> str:
    endpoints = target["endpoints"]
    environment = str(target["environment"]["name"]).lower()
    production = environment == "prod"
    release_channel = str(endpoints["release_channel"])
    replacements = (
        (DISTRIBUTION_STAGE_URL, str(endpoints["installer_base_url"])),
        (HOSTED_STAGE_PLATFORM_URL, str(endpoints["app_url"])),
        ("YOKE_CHANNEL=latest", f"YOKE_CHANNEL={release_channel}"),
        ("stage.upyoke.com", "upyoke.com" if production else "stage.upyoke.com"),
        ("public Stage", "public Production" if production else "public Stage"),
        ("Stage hosted", "Production hosted" if production else "Stage hosted"),
        ("Stage platform", "Production platform" if production else "Stage platform"),
        ("live Stage", "live Production" if production else "live Stage"),
        ("Stage browser", "Production browser" if production else "Stage browser"),
        ("Stage machine", "Production machine" if production else "Stage machine"),
        (
            "Stage onboarding",
            "Production onboarding" if production else "Stage onboarding",
        ),
    )
    result = value
    for source, replacement in replacements:
        result = result.replace(source, replacement)
    return result


def _bind_release_channel(value: Any, channel: str) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                channel
                if key == "channel" and child in {"latest", "stable"}
                else _bind_release_channel(child, channel)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_bind_release_channel(child, channel) for child in value]
    return value


def _project(value: Any, target: Mapping[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _project(child, target) for key, child in value.items()}
    if isinstance(value, list):
        return [_project(child, target) for child in value]
    if isinstance(value, str):
        return _replace_text(value, target)
    return value


def _target_destination_keys(target: Mapping[str, Any]) -> list[str]:
    environment = str(target["environment"]["name"]).lower()
    if environment == "stage":
        selected = CHOOSE_STAGE_KEYS
    elif environment == "prod":
        selected = CHOOSE_PRODUCTION_KEYS
    else:
        raise ValueError(
            f"installer campaign does not support environment {environment!r}"
        )
    return list(selected)


def _bind_destination_actions(
    cases: list[dict[str, Any]],
    target: Mapping[str, Any],
) -> None:
    keys = _target_destination_keys(target)
    environment_id = str(target["environment"]["id"])
    for case in cases:
        raw_config = case.get("method_config")
        if not isinstance(raw_config, dict):
            continue
        variants = raw_config.get("baseline_configs")
        configs = (
            list(variants.values()) if isinstance(variants, dict) else [raw_config]
        )
        for config in configs:
            if not isinstance(config, dict):
                continue
            actions = config.get("actions")
            if not isinstance(actions, list):
                continue
            for action in actions:
                if (
                    isinstance(action, dict)
                    and action.get("step") == "destination-picker"
                ):
                    action["keys"] = list(keys)
                    action["target_environment_id"] = environment_id


def installer_campaign_cases_for_target(
    target: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return concrete current cases whose endpoints all come from *target*."""
    cases = _project(
        deepcopy(list(CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES)),
        target,
    )
    assert isinstance(cases, list)
    cases = _bind_release_channel(
        cases,
        str(target["endpoints"]["release_channel"]),
    )
    assert isinstance(cases, list)
    _bind_destination_actions(cases, target)
    for case in cases:
        require_case_target(case, target)
    return cases


__all__ = ["installer_campaign_cases_for_target"]
