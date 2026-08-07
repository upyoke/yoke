"""Unit tests for desired-pin vs health-probe agreement."""

from __future__ import annotations

import pytest

from yoke_cli.commands.release_pin_agreement import (
    accepted_environment_targets,
    environment_id_for_target,
    evaluate_pin_health_agreement,
    format_accepted_environment_targets,
)


# Platform-shaped capability map: target keys differ from environment names.
PLATFORM_RELEASE_PIN = {
    "environment_by_target": {
        "stage": "yoke-api-stage",
        "production": "yoke-api-prod",
    }
}
PLATFORM_ENVIRONMENTS = [
    {"id": "yoke-api-stage", "name": "stage"},
    {"id": "yoke-api-prod", "name": "prod"},
]


@pytest.mark.parametrize(
    ("token", "expected_id"),
    (
        ("stage", "yoke-api-stage"),
        ("production", "yoke-api-prod"),
        ("yoke-api-stage", "yoke-api-stage"),
        ("yoke-api-prod", "yoke-api-prod"),
        ("prod", "yoke-api-prod"),
    ),
)
def test_platform_environment_tokens_resolve(
    token: str, expected_id: str
) -> None:
    assert (
        environment_id_for_target(
            PLATFORM_RELEASE_PIN,
            token,
            environments=PLATFORM_ENVIRONMENTS,
        )
        == expected_id
    )


def test_environment_id_for_target_reads_capability_map() -> None:
    settings = {
        "environment_by_target": {
            "canary": "service-canary",
            "customer-east": "service-customer-east",
        }
    }
    assert environment_id_for_target(settings, "canary") == "service-canary"
    assert environment_id_for_target(settings, "missing") is None


def test_environment_id_for_target_accepts_mapped_environment_id() -> None:
    settings = {
        "environment_by_target": {"production": "yoke-api-prod"},
    }
    assert environment_id_for_target(settings, "yoke-api-prod") == "yoke-api-prod"


def test_environment_name_outside_mapped_ids_is_rejected() -> None:
    settings = {
        "environment_by_target": {"production": "yoke-api-prod"},
    }
    environments = [
        {"id": "yoke-api-prod", "name": "prod"},
        {"id": "other-env", "name": "sandbox"},
    ]
    assert (
        environment_id_for_target(settings, "sandbox", environments=environments)
        is None
    )


def test_accepted_environment_targets_lists_keys_ids_and_names() -> None:
    assert accepted_environment_targets(
        PLATFORM_RELEASE_PIN, environments=PLATFORM_ENVIRONMENTS
    ) == [
        "prod",
        "production",
        "stage",
        "yoke-api-prod",
        "yoke-api-stage",
    ]
    assert (
        format_accepted_environment_targets(
            accepted_environment_targets(
                PLATFORM_RELEASE_PIN, environments=PLATFORM_ENVIRONMENTS
            )
        )
        == "prod, production, stage, yoke-api-prod, yoke-api-stage"
    )


def test_agreement_when_probe_matches_desired_pin() -> None:
    result = evaluate_pin_health_agreement(
        desired_pin="build-43",
        probe_url="https://service.example.test/status",
        desired_path="delivery.component_pin",
        probe_url_path="monitoring.status_url",
        served_pin_response_path="build.release",
        opener=lambda _url: {"build": {"release": "build-43"}},
    )
    assert result.agreed is True
    assert result.served_pin == "build-43"
    assert result.error is None


def test_disagreement_when_probe_reports_older_engine() -> None:
    result = evaluate_pin_health_agreement(
        desired_pin="build-43",
        probe_url="https://service.example.test/status",
        desired_path="delivery.component_pin",
        probe_url_path="monitoring.status_url",
        served_pin_response_path="build.release",
        opener=lambda _url: {"build": {"release": "build-42"}},
    )
    assert result.agreed is False
    assert result.desired_pin == "build-43"
    assert result.served_pin == "build-42"


def test_missing_desired_pin_is_an_error() -> None:
    result = evaluate_pin_health_agreement(
        desired_pin=None,
        probe_url="https://service.example.test/status",
        desired_path="delivery.component_pin",
        probe_url_path="monitoring.status_url",
        served_pin_response_path="build.release",
    )
    assert result.agreed is False
    assert result.error == "delivery.component_pin is unset"


def test_missing_probe_url_is_an_error() -> None:
    result = evaluate_pin_health_agreement(
        desired_pin="build-43",
        probe_url=None,
        desired_path="delivery.component_pin",
        probe_url_path="monitoring.status_url",
        served_pin_response_path="build.release",
    )
    assert result.agreed is False
    assert result.error == "monitoring.status_url is unset"


def test_missing_configured_response_leaf_is_an_error() -> None:
    result = evaluate_pin_health_agreement(
        desired_pin="build-43",
        probe_url="https://service.example.test/status",
        desired_path="delivery.component_pin",
        probe_url_path="monitoring.status_url",
        served_pin_response_path="build.release",
        opener=lambda _url: {"build": {}},
    )
    assert result.agreed is False
    assert "build.release" in (result.error or "")
