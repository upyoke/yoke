"""Tests for https doctor --only validation against caller project-local roster."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yoke_cli.commands.adapters.doctor_https_compose import (
    https_relay_needed,
    partition_only_slugs,
    prepare_https_only_payload,
)
from yoke_core.engines.doctor_project_checks import Discovery
from yoke_core.engines.doctor_registry_types import HealthCheck


def test_partition_keeps_checkout_declared_slugs_local() -> None:
    local, relay = partition_only_slugs(
        "HC-shipped-doctrine-path-portability,HC-status-consistency",
        {"shipped-doctrine-path-portability"},
    )
    assert local == ["shipped-doctrine-path-portability"]
    assert relay == "HC-status-consistency"


def test_partition_all_local_drops_relay_only() -> None:
    local, relay = partition_only_slugs(
        "shipped-doctrine-path-portability",
        {"shipped-doctrine-path-portability"},
    )
    assert local == ["shipped-doctrine-path-portability"]
    assert relay is None


def test_prepare_https_only_payload_strips_checkout_declared_slug() -> None:
    project_hc = HealthCheck(
        slug="shipped-doctrine-path-portability",
        name="Shipped doctrine path portability",
        fn=lambda *_a, **_k: None,
    )
    with (
        patch(
            "yoke_core.engines.doctor_https_only.checkout_root_for_project",
            return_value=Path("/target/yoke"),
        ),
        patch(
            "yoke_core.engines.doctor_https_only.discover_project_checks",
            return_value=Discovery([project_hc], []),
        ),
    ):
        relay_payload, local_slugs = prepare_https_only_payload({
            "project": "yoke",
            "only": "HC-shipped-doctrine-path-portability",
            "quick": False,
            "full": False,
        })

    assert local_slugs == ["shipped-doctrine-path-portability"]
    assert "only" not in relay_payload
    assert https_relay_needed(relay_payload) is False


def test_prepare_https_only_payload_relays_unknown_slug() -> None:
    with (
        patch(
            "yoke_core.engines.doctor_https_only.checkout_root_for_project",
            return_value=Path("/target/yoke"),
        ),
        patch(
            "yoke_core.engines.doctor_https_only.discover_project_checks",
            return_value=Discovery([], []),
        ),
    ):
        relay_payload, local_slugs = prepare_https_only_payload({
            "project": "yoke",
            "only": "HC-not-a-real-check",
            "quick": False,
            "full": False,
        })

    assert local_slugs == []
    assert relay_payload["only"] == "HC-not-a-real-check"
    assert https_relay_needed(relay_payload) is True
