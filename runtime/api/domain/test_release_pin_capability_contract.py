"""Generic release-pin capability validation contracts."""

from __future__ import annotations

import pytest

from yoke_core.domain.release_pin_capability import validate_settings


def _settings() -> dict:
    return {
        "desired_pin_path": "delivery.component_pin",
    }


def test_record_only_capability_needs_no_probe_contract() -> None:
    validate_settings(_settings())


def test_unknown_routing_settings_are_refused() -> None:
    with pytest.raises(ValueError, match="unknown setting"):
        validate_settings(
            {
                **_settings(),
                "unexpected_route": "customer-east",
            }
        )


def test_complete_probe_contract_accepts_project_owned_paths() -> None:
    validate_settings(
        {
            **_settings(),
            "probe_url_path": "monitoring.status_url",
            "served_pin_response_path": "build.release",
        }
    )


@pytest.mark.parametrize(
    ("configured_key", "configured_value", "missing_key"),
    (
        ("probe_url_path", "monitoring.status_url", "served_pin_response_path"),
        ("served_pin_response_path", "build.release", "probe_url_path"),
    ),
)
def test_partial_probe_contract_is_refused(
    configured_key: str,
    configured_value: str,
    missing_key: str,
) -> None:
    with pytest.raises(ValueError, match=missing_key):
        validate_settings({**_settings(), configured_key: configured_value})


@pytest.mark.parametrize(
    "key",
    ("desired_pin_path", "probe_url_path", "served_pin_response_path"),
)
def test_configured_paths_reject_empty_segments(key: str) -> None:
    settings = {
        **_settings(),
        "probe_url_path": "monitoring.status_url",
        "served_pin_response_path": "build.release",
        key: "invalid..path",
    }
    with pytest.raises(ValueError, match=key):
        validate_settings(settings)
