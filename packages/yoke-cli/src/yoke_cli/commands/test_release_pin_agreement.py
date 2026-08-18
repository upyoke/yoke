"""Unit tests for desired-pin vs health-probe agreement."""

from __future__ import annotations

from yoke_cli.commands.release_pin_agreement import (
    evaluate_pin_health_agreement,
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
