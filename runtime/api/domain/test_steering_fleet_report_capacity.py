"""Lanes against cap, per machine, on the report the seat reads before launching.

A machine at its cap is exactly the one launch eligibility drops, so a report
built only from launchable surfaces would show the full box as absent rather
than as full. The capacity line is read from the relay rows directly for that
reason, and it appears even when nothing on that machine is launchable.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    NOW,
    PROJECT_ID,
    compose as _compose,
    seed_session,
    seed_steering_scope,
)
from yoke_contracts.machine_config.machine_capacity import (
    CAP_SOURCE_DERIVED,
    CAP_SOURCE_SETTING,
)
from yoke_core.domain.session_launch_capacity import RELAY_PREDATES_CAPACITY_REASON
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body

MACHINE = "machine-1"


def _publish(conn, reading: dict | None) -> None:
    """Stand in for what the relay heartbeat writes on this machine's row."""
    conn.execute(
        "UPDATE session_relays SET machine_capacity = %s WHERE machine_id = %s",
        (None if reading is None else json.dumps(reading), MACHINE),
    )
    conn.commit()


def _reading(**overrides) -> dict:
    reading = {
        "total_memory_bytes": 64 * 1024**3,
        "free_memory_bytes": 8 * 1024**3,
        "load_average_1m": 4.5,
        "core_count": 12,
        "max_worker_lanes": 4,
        "cap_source": CAP_SOURCE_SETTING,
        "observed_at": NOW,
    }
    reading.update(overrides)
    return reading


@pytest.fixture
def fleet(test_db):
    return seed_steering_scope(test_db)


def test_the_capacity_line_names_lanes_against_cap_and_where_the_cap_came_from(fleet):
    _publish(fleet, _reading())

    body = report_body(_compose(fleet))

    assert "capacity lanes 2/4 · free 8.0 GB · load 4.5 on 12 cores" in body
    assert "cap from max_worker_lanes" in body


def test_a_derived_cap_says_which_memory_reading_it_came_from(fleet):
    _publish(fleet, _reading(cap_source=CAP_SOURCE_DERIVED, max_worker_lanes=104))

    assert "cap derived from 64.0 GB total memory" in report_body(_compose(fleet))


def test_a_machine_at_its_cap_is_marked_and_still_listed_without_a_surface(fleet):
    # Eligibility drops a full machine, so this line is the only place the
    # seat learns the box exists and is the reason nothing is launchable.
    _publish(fleet, _reading(max_worker_lanes=2))

    body = report_body(_compose(fleet))

    assert "AT CAP, launches refuse" in body
    assert "launch balance  machine-1" in body


def test_a_relay_publishing_no_reading_says_so_rather_than_reading_as_roomy(fleet):
    _publish(fleet, None)

    body = report_body(_compose(fleet))

    assert (
        f"capacity lanes 2/? · capacity unreported ({RELAY_PREDATES_CAPACITY_REASON})"
        in body
    )
    assert (
        "update that machine's relay to publish memory, load, and its lane cap" in body
    )


def test_launches_already_assigned_there_count_against_the_cap(fleet):
    # A launch on its way to the machine has no session yet; counting only
    # sessions would let a burst of launches all pass the same free lane.
    _publish(fleet, _reading())
    fleet.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, body, body_sha256, selector_snapshot, "
        "created_at, expires_at) "
        "VALUES ('msg-inflight', %s, 'launch instruction', 'sha', '{}', %s, %s)",
        (ACTOR_ID, NOW, "2026-08-26T23:00:00Z"),
    )
    fleet.execute(
        "INSERT INTO session_launches "
        "(launch_id, requester_actor_id, project_id, requested_surface, "
        "selected_surface, allow_surface_fallback, message_id, state, "
        "deadline_at, created_at, origin, assigned_machine_id) "
        "VALUES ('launch-inflight', %s, %s, 'codex-cli', 'codex-cli', 0, "
        "'msg-inflight', 'assigned', %s, %s, 'steering', %s)",
        (ACTOR_ID, PROJECT_ID, "2026-08-26T13:00:00Z", NOW, MACHINE),
    )
    fleet.commit()

    capacity = _compose(fleet).machine_capacity

    assert [(entry.machine_id, entry.live_lanes) for entry in capacity] == [
        (MACHINE, 3)
    ]


def test_the_projection_carries_the_same_reading_the_line_rendered(fleet):
    _publish(fleet, _reading(max_worker_lanes=2))

    published = report_dict(_compose(fleet))["machine_capacity"]

    assert [entry["machine_id"] for entry in published] == [MACHINE]
    assert published[0]["at_capacity"] is True
    assert published[0]["max_worker_lanes"] == 2
    assert published[0]["summary"].startswith("lanes 2/2 · free 8.0 GB")


def test_a_machine_serving_another_project_is_not_reported_here(fleet):
    _publish(fleet, _reading())
    fleet.execute(
        "INSERT INTO session_relays "
        "(relay_id, actor_id, machine_id, hostname, surface_versions, "
        "project_checkouts, first_seen_at, last_seen_at, connected_until, state) "
        "VALUES ('relay-2', %s, 'machine-2', 'other-host', '{}', %s, %s, %s, %s, "
        "'active')",
        (ACTOR_ID, json.dumps([PROJECT_ID + 1]), NOW, NOW, "2026-08-26T23:00:00Z"),
    )
    fleet.commit()

    assert [c.machine_id for c in _compose(fleet).machine_capacity] == [MACHINE]


def test_an_ended_session_stops_occupying_a_lane(fleet):
    # The lane frees when the session ends; counting it would keep a machine
    # at its cap long after the worker that filled it was gone.
    _publish(fleet, _reading())
    before = _compose(fleet).machine_capacity[0].live_lanes
    seed_session(fleet, "gone-worker", ended_at=NOW)
    fleet.commit()

    assert _compose(fleet).machine_capacity[0].live_lanes == before
