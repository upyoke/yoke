"""Unit tests for desired-pin vs health-probe agreement."""

from __future__ import annotations

from yoke_cli.commands.release_pin_agreement import (
    DESIRED_PIN_SETTINGS_PATH,
    evaluate_pin_health_agreement,
    environment_id_for_target,
)


def test_environment_id_for_target_reads_capability_map() -> None:
    settings = {
        "environment_by_target": {
            "stage": "yoke-api-stage",
            "production": "yoke-api-prod",
        }
    }
    assert environment_id_for_target(settings, "stage") == "yoke-api-stage"
    assert environment_id_for_target(settings, "missing") is None


def test_agreement_when_probe_matches_desired_pin() -> None:
    result = evaluate_pin_health_agreement(
        desired_pin="0.1.1+launch.187",
        probe_url="https://example.test/v1/health",
        opener=lambda _url: {"engine_version": "0.1.1+launch.187"},
    )
    assert result.agreed is True
    assert result.served_engine_version == "0.1.1+launch.187"
    assert result.skipped_reason is None


def test_disagreement_when_probe_reports_older_engine() -> None:
    result = evaluate_pin_health_agreement(
        desired_pin="0.1.1+launch.182",
        probe_url="https://example.test/v1/health",
        opener=lambda _url: {"engine_version": "0.1.1+launch.181"},
    )
    assert result.agreed is False
    assert result.desired_pin == "0.1.1+launch.182"
    assert result.served_engine_version == "0.1.1+launch.181"


def test_skip_when_desired_pin_unset() -> None:
    result = evaluate_pin_health_agreement(
        desired_pin=None,
        probe_url="https://example.test/v1/health",
    )
    assert result.agreed is False
    assert DESIRED_PIN_SETTINGS_PATH in (result.skipped_reason or "")
