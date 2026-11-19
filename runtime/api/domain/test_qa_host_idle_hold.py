"""Idle hosts of parked or exited holders return to the line (YOK-5511).

The measured miss: a walk parked on a HUMAN_GATE in awaiting_walk_review kept
its host lease for five hours, and a host set queued behind it kept partial
reservations on three other hosts, until a steering operator released them.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from runtime.api.domain.agent_mission_qa_test_support import (
    ACTOR,
    _materialize_mission,
    _request,
)
from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.qa_host_turns_test_support import _execution_wait, _notices
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
from yoke_core.domain.coordination_claims import acquire, active_claim, get_claim
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import prepare_agent_mission_contract
from yoke_core.domain.machine_reset_debt import reset_owed
from yoke_core.domain.qa_host_idle_hold import (
    IDLE_HOLD_RELEASED_REASON,
    IDLE_HOLD_RESERVATION_REASON,
    release_idle_host_holds,
)
from yoke_core.domain.qa_host_set_turns import record_host_wait
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.work_claim_targets import make_qa_admission_target

ITEM = 7841
LATER = timedelta(days=1)


@pytest.fixture
def review_walk(test_db, tmp_path, monkeypatch):
    """A mission walk in awaiting_walk_review holding its primary host lease."""
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_qa_session(test_db, ACTOR.session_id)
    requirement = _materialize_mission(test_db, item_id=ITEM)
    execution = begin_plan_execution(
        test_db,
        item_id=ITEM,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    request = _request(
        "test_machine.plan_case.begin",
        item_id=ITEM,
        execution_id=str(execution["id"]),
        requirement_id=requirement,
        ordinal=0,
    )
    begun = handle_plan_case_begin(request)
    assert begun.primary_success, begun.error
    original = begun.result_payload["execution"]
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        prepared = prepare_agent_mission_contract(original)
    finally:
        clear_host_control_factory()
    ready = handle_agent_mission_ready(
        request.model_copy(
            update={
                "function": "test_machine.mission.ready",
                "payload": {**request.payload, **prepared},
            }
        )
    )
    assert ready.primary_success, ready.error
    # The walk handed back for review; review keeps the primary lease.
    test_db.execute(
        "UPDATE qa_plan_executions SET state='awaiting_walk_review' WHERE id=%s",
        (str(execution["id"]),),
    )
    test_db.commit()
    current = lock_plan_execution(test_db, str(execution["id"]))
    test_db.rollback()
    assert current["state"] == "awaiting_walk_review"
    machine = original["settings"]["resource_name"]
    lease = active_claim(test_db, make_qa_admission_target(machine))
    assert lease is not None and lease.id == original["lease_id"]
    return str(execution["id"]), machine, lease.id


def _set_session(conn, session_id, **columns):
    assignments = ",".join(f"{name}=%s" for name in columns)
    conn.execute(
        f"UPDATE harness_sessions SET {assignments} WHERE session_id=%s",
        (*columns.values(), session_id),
    )
    conn.commit()


def _assert_released_and_waiter_woken(conn, review_walk, bodies):
    execution_id, machine, lease_id = review_walk
    assert release_idle_host_holds(conn, now=utc_now() + LATER) == [lease_id]
    assert not get_claim(conn, lease_id).is_active
    assert reset_owed(conn, machine) == "fresh-host"
    current = lock_plan_execution(conn, execution_id)
    conn.rollback()
    assert current["state"] == "aborted"
    assert current["release_reason"].startswith(IDLE_HOLD_RELEASED_REASON)
    assert (
        "start the walk again with `yoke qa plan run --item" in current["release_reason"]
    )
    assert active_claim(conn, make_qa_admission_target(machine)).session_id == "next"
    assert f"QA host turn ready: {machine}" in bodies[0]
    # Any other notice is the owner's: its walk stopped with captures owed review.
    for body in bodies[1:]:
        assert f"QA plan execution {execution_id}" in body
        assert "stopped as aborted" in body


def test_human_gate_park_in_walk_review_returns_the_host_after_the_limit(
    test_db, review_walk, monkeypatch
):
    bodies = _notices(monkeypatch)
    _, machine, lease_id = review_walk
    seed_qa_session(test_db, "next")
    _execution_wait(test_db, "next", test_machine=machine)
    _set_session(
        test_db, ACTOR.session_id, mode="parked", quiet_reason="HUMAN_GATE: approve"
    )
    # Inside the limit nothing moves.
    assert release_idle_host_holds(test_db, now=utc_now()) == []
    assert get_claim(test_db, lease_id).is_active
    _assert_released_and_waiter_woken(test_db, review_walk, bodies)


def test_exited_process_holding_claims_returns_the_host(
    test_db, review_walk, monkeypatch
):
    bodies = _notices(monkeypatch)
    _, machine, _ = review_walk
    seed_qa_session(test_db, "next")
    _execution_wait(test_db, "next", test_machine=machine)
    _set_session(
        test_db,
        ACTOR.session_id,
        last_tool_call_at=utc_now() - timedelta(minutes=5),
        native_process_gone_at=utc_now(),
    )
    held = query_one(
        test_db,
        "SELECT COUNT(*) AS n FROM work_claims WHERE session_id=%s AND released_at IS NULL",
        (ACTOR.session_id,),
    )
    assert held["n"] >= 1
    _assert_released_and_waiter_woken(test_db, review_walk, bodies)


def test_unparked_live_holder_keeps_its_host(test_db, review_walk):
    _, _, lease_id = review_walk
    assert release_idle_host_holds(test_db, now=utc_now() + LATER) == []
    assert get_claim(test_db, lease_id).is_active


def test_waiting_partial_host_set_returns_its_reservations_and_keeps_its_place(
    test_db, monkeypatch
):
    bodies = _notices(monkeypatch)
    seed_qa_session(test_db, "parked-holder", "walker")
    a, b = "lab-a", "lab-b"
    held = acquire(test_db, make_qa_admission_target(a), "parked-holder")
    walker = _execution_wait(test_db, "walker", test_machine=a)
    execution = query_one(test_db, "SELECT * FROM qa_plan_executions WHERE id=%s", (walker,))
    record_host_wait(
        test_db,
        {**execution, "roster": []},
        test_machine=a,
        rationale="busy",
        test_machines=(a, b),
    )
    places = test_db.execute(
        "SELECT test_machine,state,queued_at FROM qa_test_machine_waits "
        "WHERE qa_plan_execution_id=%s AND state IN ('waiting','reserved') "
        "ORDER BY test_machine",
        (walker,),
    ).fetchall()
    assert [(r[0], r[1]) for r in places] == [(a, "waiting"), (b, "reserved")]
    partial = active_claim(test_db, make_qa_admission_target(b))
    assert partial.session_id == "walker" and bodies == []
    _set_session(test_db, "parked-holder", mode="parked", quiet_reason="HUMAN_GATE")

    assert release_idle_host_holds(test_db, now=utc_now() + LATER) == [held.id]

    assert not get_claim(test_db, held.id).is_active
    intent = query_one(
        test_db, "SELECT release_reason_intent FROM work_claims WHERE id=%s", (partial.id,)
    )
    assert not get_claim(test_db, partial.id).is_active
    assert intent["release_reason_intent"] == IDLE_HOLD_RESERVATION_REASON
    after = test_db.execute(
        "SELECT test_machine,state,queued_at FROM qa_test_machine_waits "
        "WHERE qa_plan_execution_id=%s AND state IN ('waiting','reserved') "
        "ORDER BY test_machine",
        (walker,),
    ).fetchall()
    # The execution kept its one place on both hosts and now holds the set.
    assert [(r[0], r[1]) for r in after] == [(a, "reserved"), (b, "reserved")]
    assert {r[2] for r in after} == {places[0][2]}
    assert len(bodies) == 1


def test_steering_report_alarms_on_a_parked_holder_of_a_host(test_db) -> None:
    """The one-statement holder read carries held hosts; a parked holder alarms."""
    from runtime.api.domain.steering_fleet_report_holder_read_test_support import _claim
    from runtime.api.steering_fleet_test_helpers import (
        LONG_AGO,
        NOW,
        PROJECT_ID,
        seed_session,
        seed_steering_scope,
    )
    from yoke_core.domain.steering_fleet_report_holders import (
        claim_holders,
        quiet_holders,
        with_session_state,
    )

    fleet = seed_steering_scope(test_db)
    seed_session(fleet, "parked-walker", last_tool_call_at=LONG_AGO)
    _claim(fleet, "parked-walker", 1)
    acquire(fleet, make_qa_admission_target("lab-a"), "parked-walker")
    _set_session(fleet, "parked-walker", mode="parked", quiet_reason="HUMAN_GATE")

    holders = with_session_state(
        claim_holders(fleet, project_id=PROJECT_ID, now=NOW),
        now=NOW,
        idle_after_seconds=20 * 60,
    )

    [holder] = holders
    assert holder.session_state["custody"]["qa_hosts"] == ["lab-a"]
    assert holder.session_state["intent"]["state"] == "parked"
    assert quiet_holders(holders) == holders
