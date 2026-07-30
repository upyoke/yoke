"""Release-channel coherence tests for materialized QA cases."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL, HOSTED_PLATFORM_URL
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    _yoke_endpoints,
    require_case_target,
)


@pytest.mark.parametrize(
    "environment, expected",
    [("stage", "latest"), ("prod", "stable")],
)
def test_hosted_environment_projects_its_release_channel(
    environment,
    expected,
) -> None:
    endpoints = _yoke_endpoints(environment, "upyoke")
    target = {"environment": {"name": environment}, "endpoints": endpoints}

    rendered = json.dumps(installer_campaign_cases_for_target(target))

    assert endpoints["release_channel"] == expected
    assert f"YOKE_CHANNEL={expected}" in rendered
    assert f'"channel": "{expected}"' in rendered


@pytest.mark.parametrize(
    "case",
    [
        {"method_config": {"setup_operations": [{"channel": "latest"}]}},
        {"entry_surface": "YOKE_CHANNEL=latest /bin/sh"},
    ],
)
def test_case_guard_rejects_opposite_release_channel(case) -> None:
    target = {
        "environment": {"name": "prod"},
        "endpoints": {
            "app_url": HOSTED_PLATFORM_URL,
            "api_url": f"{HOSTED_PLATFORM_URL}/api/orgs/upyoke",
            "installer_base_url": DISTRIBUTION_PROD_URL,
            "installer_url": f"{DISTRIBUTION_PROD_URL}/install",
            "release_channel": "stable",
        },
    }
    with pytest.raises(QaExecutionTargetError, match="release channel"):
        require_case_target(case, target)
