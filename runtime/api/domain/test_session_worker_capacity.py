"""A MAIN can staff one worker without spending its worker allowance."""

from __future__ import annotations

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_launch_capacity import live_lane_count, live_lane_counts
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)
from runtime.api.domain.test_session_launch_capacity import (
    MACHINE,
    _eligibility,
    _live_session,
    _publish_capacity,
)


def _counts(conn, expected):
    now = parse_instant(NOW)
    assert live_lane_count(conn, machine_id=MACHINE, now=now) == expected
    assert live_lane_counts(conn, now=now).get(MACHINE, 0) == expected


def _operator_launch(conn, key):
    """A launch the operator started with no requesting session."""
    launch = assigned_launch(conn, key=key, machine_id=MACHINE)
    conn.execute(
        "UPDATE session_launches SET requester_session_id=NULL WHERE launch_id=?",
        (launch.launch_id,),
    )
    return launch


@pytest.mark.parametrize("operator_launched", [False, True])
def test_main_at_one_worker_cap_can_staff_first_worker_but_not_second(
    operator_launched,
):
    conn = launch_connection()
    add_relay(conn)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id, machine_id) "
        "VALUES ('main', 10, ?)",
        (MACHINE,),
    )
    if operator_launched:
        launch = _operator_launch(conn, "main")
        conn.execute(
            "UPDATE session_launches SET registered_session_id='main' "
            "WHERE launch_id=?",
            (launch.launch_id,),
        )
    _publish_capacity(conn, max_worker_lanes=1)
    _counts(conn, 0)
    assert [relay.machine_id for relay in _eligibility(conn).relays] == [MACHINE]

    _live_session(conn, "first-worker")
    _counts(conn, 1)
    assert _eligibility(conn).relays == ()


@pytest.mark.parametrize("column", ["ended_at", "terminated_at"])
def test_finished_worker_releases_scalar_and_grouped_occupancy(column):
    conn = launch_connection()
    add_relay(conn)
    _live_session(conn, "worker")
    _publish_capacity(conn, max_worker_lanes=1)
    _counts(conn, 1)
    conn.execute(
        f"UPDATE harness_sessions SET {column}=? WHERE session_id='worker'", (NOW,)
    )
    _counts(conn, 0)
    assert [relay.machine_id for relay in _eligibility(conn).relays] == [MACHINE]


def test_launch_registration_handoff_counts_once_even_with_multiple_correlations():
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, machine_id=MACHINE)
    _counts(conn, 1)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id, machine_id) "
        "VALUES ('worker', 10, ?)",
        (MACHINE,),
    )
    conn.execute(
        "UPDATE session_launches SET registered_session_id='worker' WHERE launch_id=?",
        (launch.launch_id,),
    )
    _counts(conn, 1)
    duplicate = assigned_launch(conn, key="correlated-again", machine_id=MACHINE)
    conn.execute(
        "UPDATE session_launches SET registered_session_id='worker' WHERE launch_id=?",
        (duplicate.launch_id,),
    )
    _counts(conn, 1)


@pytest.mark.parametrize("state", ["assigned", "launching", "awaiting_registration"])
def test_inflight_worker_reserves_only_until_its_deadline(state):
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, machine_id=MACHINE)
    conn.execute(
        "UPDATE session_launches SET state=? WHERE launch_id=?",
        (state, launch.launch_id),
    )
    _counts(conn, 1)
    conn.execute(
        "UPDATE session_launches SET deadline_at=? WHERE launch_id=?",
        (NOW, launch.launch_id),
    )
    _counts(conn, 0)


def test_inflight_operator_launch_reserves_no_worker_lane():
    conn = launch_connection()
    add_relay(conn)
    _operator_launch(conn, "operator-main")
    _publish_capacity(conn, max_worker_lanes=1)
    _counts(conn, 0)
    assert [relay.machine_id for relay in _eligibility(conn).relays] == [MACHINE]
