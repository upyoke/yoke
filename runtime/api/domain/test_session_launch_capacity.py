"""Launch preview refuses past a machine's lane cap, with the numbers."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant

from yoke_core.domain.session_launch_capacity import (
    MACHINE_AT_CAPACITY,
    live_lane_count,
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
        conn,
        project_id=10,
        surface="codex-cli",
        machine_id=None,
        now=parse_instant(NOW),
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
        conn, machine_id=MACHINE, capacity_document=None, now=parse_instant(NOW)
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


@pytest.mark.parametrize(
    "observed",
    [
        "2026-08-22T12:00:00.123456Z",
        "2026-08-22T17:45:00.123456+05:45",
        "2026-08-22T08:00:00.123456-04:00",
    ],
)
def test_capacity_keeps_native_observation_until_json_projection(observed) -> None:
    reading = machine_capacity(
        launch_connection(),
        machine_id=MACHINE,
        capacity_document={"observed_at": observed, "max_worker_lanes": 3},
        now=parse_instant(NOW),
    )
    assert reading.observed_at == datetime(
        2026, 8, 22, 12, 0, 0, 123456, tzinfo=timezone.utc
    )
    payload = json.loads(json.dumps(reading.to_dict()))
    assert payload["observed_at"] == "2026-08-22T12:00:00.123456Z"
    assert payload["summary"] == reading.summary()
    assert payload["at_capacity"] is False
    assert payload["machine_id"] == MACHINE


def test_capacity_projection_keeps_absent_observation_null() -> None:
    reading = machine_capacity(
        launch_connection(),
        machine_id=MACHINE,
        capacity_document=None,
        now=parse_instant(NOW),
    )
    assert reading.observed_at is None
    assert json.loads(json.dumps(reading.to_dict()))["observed_at"] is None


@pytest.mark.parametrize(
    "observed", ["", "2026-08-22", "2026-08-22T12:00:00", "2026-08-22T12:00:00-00:00"]
)
def test_capacity_constructor_refuses_unverifiable_observation(observed) -> None:
    reading = machine_capacity(
        launch_connection(),
        machine_id=MACHINE,
        capacity_document=None,
        now=parse_instant(NOW),
    )
    with pytest.raises(InvalidInstant):
        replace(reading, observed_at=observed)


@pytest.mark.parametrize(
    "clock", [NOW, "2026-08-22T17:30:00+05:30", datetime(2026, 8, 22), None, 0, False]
)
def test_internal_capacity_reference_refuses_before_any_sql(clock):
    from yoke_core.domain.steering_fleet_report_capacity import (
        launchable_surfaces,
        machine_capacities,
    )

    class NoSQL:
        def execute(self, *_args, **_kwargs):
            pytest.fail("Native reference clock admission must precede SQL")

    from yoke_core.domain.session_launch_level_placement import place_level
    from yoke_core.domain.session_launch_level_selection import preview_level_launch

    conn = NoSQL()
    calls = (
        lambda: live_lane_count(conn, machine_id=MACHINE, now=clock),
        lambda: machine_capacity(
            conn, machine_id=MACHINE, capacity_document=None, now=clock
        ),
        lambda: derive_launch_eligibility(
            conn, project_id=10, surface="codex-cli", machine_id=None, now=clock
        ),
        lambda: launchable_surfaces(conn, project_id=10, now=clock),
        lambda: machine_capacities(conn, project_id=10, now=clock),
        lambda: place_level(
            conn,
            auth=authorization(),
            project_id=10,
            level="opaque",
            machine_id=None,
            now=clock,
            eligibility=derive_launch_eligibility,
        ),
        lambda: preview_level_launch(
            conn,
            auth=authorization(),
            request=LaunchRequest(
                project_id=10,
                executor_surface="",
                instructions="",
                idempotency_key="",
                level="opaque",
            ),
            now=clock,
            eligibility=derive_launch_eligibility,
        ),
    )
    for call in calls:
        with pytest.raises(InvalidInstant):
            call()


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
@pytest.mark.parametrize("microsecond", [0, 123456])
def test_native_lane_deadline_comparison_preserves_exact_microseconds(
    zone, microsecond
):
    from runtime.api.fixtures.native_instant_database import blank_database

    anchor = datetime(1969, 12, 31, 23, 59, 59, microsecond, tzinfo=timezone.utc)
    supplied = anchor.astimezone(timezone(timedelta(minutes=330)))
    with blank_database() as conn:
        conn.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
        conn.execute(
            "CREATE TABLE harness_sessions (machine_id TEXT, ended_at TIMESTAMPTZ)"
        )
        conn.execute(
            "CREATE TABLE session_launches (assigned_machine_id TEXT, state TEXT, registered_session_id TEXT, deadline_at TIMESTAMPTZ)"
        )
        conn.execute("INSERT INTO harness_sessions VALUES (%s, NULL)", (MACHINE,))
        for delta in (-1, 0, 1):
            conn.execute(
                "INSERT INTO session_launches VALUES (%s, 'assigned', NULL, %s)",
                (MACHINE, anchor + timedelta(microseconds=delta)),
            )
        assert live_lane_count(conn, machine_id=MACHINE, now=supplied) == 2
        assert conn.execute("SHOW TimeZone").fetchone()[0] == zone
        clocks = conn.execute("SELECT deadline_at FROM session_launches").fetchall()
        assert all(isinstance(row[0], datetime) and row[0].tzinfo for row in clocks)
        assert sorted(row[0] for row in clocks) == [
            anchor + timedelta(microseconds=delta) for delta in (-1, 0, 1)
        ]
