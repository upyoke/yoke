"""The lane cap a machine publishes: configured, derived from memory, or unknown."""

from __future__ import annotations

from yoke_contracts.machine_config import machine_capacity as capacity_module
from yoke_contracts.machine_config.machine_capacity import (
    CAP_SOURCE_DERIVED,
    CAP_SOURCE_SETTING,
    CAP_SOURCE_UNREADABLE,
    configured_lane_cap,
    derived_lane_cap,
    format_bytes,
    observe_machine_capacity,
    sanitize_machine_capacity,
)

GIB = 1024**3


def test_the_derived_cap_is_what_memory_leaves_after_the_reserve() -> None:
    assert derived_lane_cap(48 * GIB) == 72
    assert derived_lane_cap(16 * GIB) == 8
    # A box smaller than the reserve still carries one lane rather than none.
    assert derived_lane_cap(8 * GIB) == 1
    assert derived_lane_cap(None) is None


def test_a_configured_cap_wins_over_the_derivation() -> None:
    assert configured_lane_cap({"max_worker_lanes": "7"}) == 7
    assert configured_lane_cap({"max_worker_lanes": 0}) is None
    assert configured_lane_cap({"max_worker_lanes": "lots"}) is None
    assert configured_lane_cap({}) is None


def test_the_reading_names_where_its_cap_came_from(monkeypatch) -> None:
    monkeypatch.setattr(capacity_module, "total_memory_bytes", lambda: 48 * GIB)
    monkeypatch.setattr(capacity_module, "free_memory_bytes", lambda: 44 * 1024**2)
    monkeypatch.setattr(capacity_module, "load_average_1m", lambda: 31.2)
    monkeypatch.setattr(capacity_module, "core_count", lambda: 18)

    derived = observe_machine_capacity({}, observed_at="2026-09-03T20:00:00Z")
    assert (derived.max_worker_lanes, derived.cap_source) == (72, CAP_SOURCE_DERIVED)
    assert derived.to_dict()["free_memory_bytes"] == 44 * 1024**2
    assert derived.to_dict()["core_count"] == 18

    configured = observe_machine_capacity(
        {"max_worker_lanes": "12"}, observed_at="2026-09-03T20:00:00Z"
    )
    assert (configured.max_worker_lanes, configured.cap_source) == (
        12,
        CAP_SOURCE_SETTING,
    )

    monkeypatch.setattr(capacity_module, "total_memory_bytes", lambda: None)
    unknown = observe_machine_capacity({}, observed_at="2026-09-03T20:00:00Z")
    assert unknown.max_worker_lanes is None
    assert unknown.cap_source == CAP_SOURCE_UNREADABLE


def test_sanitizing_keeps_only_typed_capacity_fields() -> None:
    cleaned = sanitize_machine_capacity(
        {
            "total_memory_bytes": "51539607552",
            "free_memory_bytes": -5,
            "load_average_1m": "31.2",
            "core_count": 18,
            "max_worker_lanes": True,
            "cap_source": "derived_from_total_memory",
            "observed_at": "2026-09-03T20:00:00Z",
            "accessToken": "must-not-travel",
        }
    )
    assert cleaned["total_memory_bytes"] == 51539607552
    assert cleaned["free_memory_bytes"] is None
    assert cleaned["load_average_1m"] == 31.2
    assert cleaned["max_worker_lanes"] is None
    assert "accessToken" not in cleaned
    assert sanitize_machine_capacity("not a document") == {}


def test_bytes_render_at_the_unit_a_person_reads() -> None:
    assert format_bytes(44 * 1024**2) == "44 MB"
    assert format_bytes(48 * GIB) == "48.0 GB"
    assert format_bytes(None) == "unknown"
