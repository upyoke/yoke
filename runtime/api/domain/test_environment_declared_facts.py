"""An environment behaves by its declared facts, not by its name."""

from __future__ import annotations

import pytest

from yoke_contracts.api_urls import (
    DISTRIBUTION_PROD_URL,
    DISTRIBUTION_STAGE_URL,
    HOSTED_PLATFORM_URL,
    HOSTED_PROD_API_URL,
    HOSTED_STAGE_API_URL,
    HOSTED_STAGE_PLATFORM_URL,
)
from yoke_core.domain.deployment_flow_policy import validate_release_stage_policy
from yoke_core.domain.environment_declared_facts import (
    MissingEnvironmentFact,
    HOSTS_APP_PATH,
    admin_connection_for_environment,
    hosted_endpoints,
    production_declared_facts,
    restricts_qa_to_self,
    serving_connection_for_environment,
    target_is_production,
)
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    _yoke_endpoints,
    require_runtime_target,
)


def _prod_facts():
    return production_declared_facts(
        app_url=HOSTED_PLATFORM_URL,
        api_url=HOSTED_PROD_API_URL,
        installer_base_url=DISTRIBUTION_PROD_URL,
        release_channel="stable",
        admin_connection="prod-db-admin",
        serving_connection="prod",
        production=True,
    )


def _stage_facts():
    return production_declared_facts(
        app_url=HOSTED_STAGE_PLATFORM_URL,
        api_url=HOSTED_STAGE_API_URL,
        installer_base_url=DISTRIBUTION_STAGE_URL,
        release_channel="latest",
        admin_connection="stage-db-admin",
        serving_connection="stage",
        production=False,
    )


def test_renamed_environment_matches_production_endpoints_and_gates(
    monkeypatch,
) -> None:
    facts = _prod_facts()
    named = hosted_endpoints("prod", facts)
    renamed = hosted_endpoints("blah", facts)

    assert renamed == named
    assert renamed["release_channel"] == "stable"
    assert renamed["app_url"] == HOSTED_PLATFORM_URL
    assert admin_connection_for_environment("blah", facts) == "prod-db-admin"
    assert serving_connection_for_environment("blah", facts) == "prod"
    assert target_is_production({"role": {"production": True}}) is True
    monkeypatch.setenv("YOKE_ENVIRONMENT", "blah")
    require_runtime_target(
        {"environment": {"name": "blah"}},
        runtime_settings=facts,
    )
    with pytest.raises(QaExecutionTargetError, match="cannot execute QA target"):
        require_runtime_target(
            {"environment": {"name": "other"}},
            runtime_settings=facts,
        )


def test_renamed_environment_matches_stage_endpoints() -> None:
    facts = _stage_facts()
    assert hosted_endpoints("blah", facts) == hosted_endpoints("stage", facts)
    assert hosted_endpoints("blah", facts)["release_channel"] == "latest"
    assert target_is_production({"role": {"production": False}}) is False


def test_undeclared_environment_refuses_endpoints_by_name() -> None:
    with pytest.raises(QaExecutionTargetError, match="does not declare"):
        _yoke_endpoints("blah")
    with pytest.raises(MissingEnvironmentFact, match=HOSTS_APP_PATH):
        hosted_endpoints("blah", {})


def test_undeclared_runtime_does_not_inherit_production_qa_gating() -> None:
    require_runtime_target({"environment": {"name": "other"}})
    assert restricts_qa_to_self({}) is False


def test_flow_qa_target_may_omit_environment_to_follow_the_run() -> None:
    stages = [
        {
            "name": "warm-up",
            "step_runner": "warm-up",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {
                "kind": "persistent_environment",
                "source_stage": "warm-up",
            },
            "verdict": {"mode": "agent_only"},
        },
    ]
    validate_release_stage_policy(stages)


def test_flow_qa_target_still_accepts_an_explicit_environment() -> None:
    stages = [
        {
            "name": "warm-up",
            "step_runner": "warm-up",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {
                "kind": "persistent_environment",
                "environment": "fixed",
                "source_stage": "warm-up",
            },
            "verdict": {"mode": "agent_only"},
        },
    ]
    validate_release_stage_policy(stages)
