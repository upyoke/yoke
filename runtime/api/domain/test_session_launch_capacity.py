"""Launch preview refuses past a machine's lane cap, with the numbers."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.session_launch_capacity import (
    MACHINE_AT_CAPACITY,
    machine_capacity,
)
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)

MACHINE = "machine-1"


def _publish_capacity(conn, *, max_worker_lanes: int | None, relay_id="relay-1"):
    document = {
        "total_memory_bytes": 48 * 1024**3,
        "free_memory_bytes": 44 * 1024**2,
        "load_average_1m": 31.2,
        "core_count": 18,
        "max_worker_lanes": max_worker_lanes,
        "cap_source": "derived_from_total_memory",
        "observed_at": NOW,
    }
    conn.execute(
        "UPDATE session_relays SET machine_capacity=? WHERE relay_id=?",
        (json.dumps(document), relay_id),
    )
    conn.commit()


def _live_session(conn, session_id: str, *, machine_id: str = MACHINE) -> None:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id, executor_surface, "
        "executor_version, machine_id, model) VALUES (?, 10, 'codex-cli', "
        "'0.148.0a15', ?, 'gpt-5')",
        (session_id, machine_id),
    )
    conn.commit()


def _eligibility(conn):
    return derive_launch_eligibility(
        conn, project_id=10, surface="codex-cli", machine_id=None, now=NOW
    )


def test_a_machine_under_its_cap_stays_eligible_and_reports_its_lanes() -> None:
    conn = launch_connection()
    add_relay(conn)
    _publish_capacity(conn, max_worker_lanes=3)
    _live_session(conn, "worker-1")
    _live_session(conn, "worker-2")

    snapshot = _eligibility(conn)

    assert [relay.machine_id for relay in snapshot.relays] == [MACHINE]
    (reading,) = snapshot.machine_capacity
    assert (reading.live_lanes, reading.max_worker_lanes) == (2, 3)
    assert reading.at_capacity is False
    assert reading.summary() == "lanes 2/3 · free 44 MB · load 31.2 on 18 cores"


def test_a_machine_at_its_cap_is_refused_with_the_numbers_and_the_recovery() -> None:
    conn = launch_connection()
    add_relay(conn)
    _publish_capacity(conn, max_worker_lanes=2)
    _live_session(conn, "worker-1")
    _live_session(conn, "worker-2")

    snapshot = _eligibility(conn)
    assert snapshot.relays == ()
    assert MACHINE_AT_CAPACITY in snapshot.rejection_codes

    with pytest.raises(SessionLaunchError) as refused:
        create_launch(
            conn,
            auth=authorization(),
            request=LaunchRequest(
                project_id=10,
                executor_surface="codex-cli",
                instructions="Inspect the current work and report evidence.",
                idempotency_key="at-cap",
            ),
            now=NOW,
        )
    assert refused.value.code == MACHINE_AT_CAPACITY
    message = str(refused.value)
    assert "lanes 2/2 · free 44 MB · load 31.2 on 18 cores" in message
    assert "cap derived from 48.0 GB total memory" in message
    assert "wait for a landing" in message
    assert "max_worker_lanes" in message
    assert "--machine" in message


def test_a_launch_still_in_flight_occupies_a_lane_before_it_registers() -> None:
    conn = launch_connection()
    add_relay(conn)
    _publish_capacity(conn, max_worker_lanes=2)
    _live_session(conn, "worker-1")
    assigned_launch(conn, key="first", machine_id=MACHINE)

    reading = machine_capacity(
        conn, machine_id=MACHINE, capacity_document=None, now=NOW
    )
    assert reading.live_lanes == 2
    assert _eligibility(conn).relays == ()


def test_a_raised_cap_readmits_the_same_machine() -> None:
    conn = launch_connection()
    add_relay(conn)
    _publish_capacity(conn, max_worker_lanes=2)
    _live_session(conn, "worker-1")
    _live_session(conn, "worker-2")
    assert _eligibility(conn).relays == ()

    _publish_capacity(conn, max_worker_lanes=4)

    assert [relay.machine_id for relay in _eligibility(conn).relays] == [MACHINE]


def test_a_relay_that_publishes_no_reading_carries_no_cap_and_says_so() -> None:
    conn = launch_connection()
    add_relay(conn)
    for index in range(5):
        _live_session(conn, f"worker-{index}")

    snapshot = _eligibility(conn)

    assert [relay.machine_id for relay in snapshot.relays] == [MACHINE]
    (reading,) = snapshot.machine_capacity
    assert reading.unreported is True
    assert reading.at_capacity is False
    assert "capacity unreported" in reading.summary()
    assert "relay_predates_capacity_readings" in reading.summary()
