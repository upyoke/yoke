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
    endpoint_declaration_state,
    hosted_endpoints,
    production_declared_facts,
    refuse_invalid_endpoint_urls,
    restricts_qa_to_self,
    serving_connection_for_environment,
    target_is_production,
)
from yoke_core.domain.environment_host_urls import (
    refuse_invalid_endpoint_url_assignments,
)
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    _generic_endpoints,
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
    with pytest.raises(MissingEnvironmentFact, match=HOSTS_APP_PATH):
        hosted_endpoints("blah", {"qa": {"hosted_runtime": True}})


def test_incomplete_endpoints_report_declared_scheme_less_hosts() -> None:
    settings = {"hosts": {"api": "app.upyoke.com"}}
    with pytest.raises(MissingEnvironmentFact, match="not a URL") as caught:
        hosted_endpoints("prod", settings)
    text = str(caught.value)
    assert "hosts.app=absent" in text
    assert "hosts.api='app.upyoke.com'" in text
    assert "replace declared-but-not-a-URL" in text
    assert "Recovery:" in text


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


def _complete_scheme_less_api() -> dict:
    facts = production_declared_facts(
        app_url=HOSTED_PLATFORM_URL,
        api_url="api.upyoke.com",
        installer_base_url=DISTRIBUTION_PROD_URL,
        release_channel="stable",
        admin_connection="prod-db-admin",
        serving_connection="prod",
        production=True,
    )
    return facts


def test_complete_scheme_less_host_is_not_a_sufficient_declaration() -> None:
    settings = _complete_scheme_less_api()
    assert endpoint_declaration_state(settings) == "incomplete"
    with pytest.raises(MissingEnvironmentFact, match="scheme-less host") as caught:
        hosted_endpoints("prod", settings)
    text = str(caught.value)
    assert "hosts.api='api.upyoke.com'" in text
    assert "hosts.app=" in text
    assert "Recovery:" in text


def test_generic_endpoints_refuse_scheme_less_hosts() -> None:
    with pytest.raises(QaExecutionTargetError, match="not an HTTP URL"):
        _generic_endpoints({"url": ""}, {"hosts": {"api": "api.upyoke.com"}})


def test_settings_write_refuses_scheme_less_host_assignment() -> None:
    with pytest.raises(ValueError, match="hosts.api must be an http\\(s\\) URL"):
        refuse_invalid_endpoint_url_assignments({"hosts.api": "api.upyoke.com"})
    refuse_invalid_endpoint_url_assignments(
        {"hosts.api": "https://api.upyoke.com"}
    )
    refuse_invalid_endpoint_urls(
        {"hosts": {"api": "https://api.upyoke.com"}}
    )
    with pytest.raises(ValueError, match="hosts.api must be an http\\(s\\) URL"):
        refuse_invalid_endpoint_urls({"hosts": {"api": "api.upyoke.com"}})
