# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from copy import deepcopy

from pathlib import Path

import pytest

from yoke_contracts.api_urls import (
    DISTRIBUTION_PROD_URL,
    DISTRIBUTION_STAGE_URL,
    HOSTED_PLATFORM_URL,
    HOSTED_PROD_API_URL,
    HOSTED_STAGE_API_URL,
    HOSTED_STAGE_PLATFORM_URL,
)

from yoke_core.domain.environment_declared_facts import production_declared_facts

from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
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


def _facts(environment: str) -> dict:
    if environment == "stage":
        return production_declared_facts(
            app_url=HOSTED_STAGE_PLATFORM_URL,
            api_url=HOSTED_STAGE_API_URL,
            installer_base_url=DISTRIBUTION_STAGE_URL,
            release_channel="latest",
            admin_connection="stage-db-admin",
            serving_connection="stage",
            production=False,
        )
    return production_declared_facts(
        app_url=HOSTED_PLATFORM_URL,
        api_url=HOSTED_PROD_API_URL,
        installer_base_url=DISTRIBUTION_PROD_URL,
        release_channel="stable",
        admin_connection="prod-db-admin",
        serving_connection="prod",
        production=True,
    )


def _target(environment: str) -> dict:
    facts = _facts(environment)
    endpoints = _yoke_endpoints(environment, settings=facts)
    return {
        "environment": {"name": environment},
        "endpoints": endpoints,
        "role": {"production": environment != "stage"},
    }
