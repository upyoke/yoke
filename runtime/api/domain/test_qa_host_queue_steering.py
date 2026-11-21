"""A walk's single Test Machine queue place is durable and steerable."""

import json
from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import _notices
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.handlers.machine_qa_queue import (
    HandOverRequest,
    PlaceRequest,
    WithdrawRequest,
    _edit,
)
from yoke_core.domain.qa_host_idle_waiters import hand_off_idle_waiter_reservations
from yoke_core.domain.qa_host_set_turns import execution_waits, record_host_wait
from yoke_core.domain.qa_host_turn_borrow import borrow_turn
from yoke_core.domain.qa_host_turns import join_host_queue
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution, roster_digest
from yoke_core.domain.steering_claims import acquire as acquire_seat
from yoke_core.domain.work_claim_targets import make_qa_admission_target

STUDIO = "test-mac-studio"
WIN = "windows-lab"
NATIVE = "windows-native-lab"
REASON = "Serve the time-sensitive QA walk"


def _target(host=WIN):
    return make_qa_admission_target(host)


@pytest.fixture
def world(test_db, monkeypatch):
    seed_qa_session(
        test_db, "operator", "current", "older", "matrix", "younger", "studio"
    )
    _notices(monkeypatch)
    return test_db


def _queue(conn, number, session, host=WIN, hosts=()):
    insert_item(conn, id=number, project_sequence=number, status="implementing")
    execution = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_executions(id,item_id,transition_id,session_id,actor_id,"
        "roster_digest,roster_json,cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,'release',%s,'1',%s,'[]',0,'active',now(),now())",
        (execution, number, session, roster_digest([])),
    )
    record_host_wait(
        conn,
        lock_plan_execution(conn, execution),
        test_machine=host,
        test_machines=hosts,
        rationale="host in use",
    )
    return execution


def _seat(conn):
    acquire_seat(conn, session_id="operator", project_id=1, reason="Steer release QA")
    conn.commit()


def _call(action, model, event, payload):
    request = FunctionCallRequest(
        function=f"test_machine.queue.{action}",
        actor=ActorContext(actor_id="1", session_id="operator"),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={"reason": REASON, **payload},
    )
    return _edit(request, model=model, event_name=event)


def _place(execution, position, host=WIN):
    return _call(
        "place",
        PlaceRequest,
        "QaHostWaiterPlaced",
        {"execution": execution, "host": host, "position": position},
    )


def _hand_over(source, receiver):
    return _call(
        "hand_over",
        HandOverRequest,
        "QaHostTurnHandedOver",
        {"from_execution": source, "to_execution": receiver, "host": WIN},
    )


def _withdraw(**selector):
    return _call("withdraw", WithdrawRequest, None, selector)


def _assert_event(conn, name):
    row = query_one(
        conn, "SELECT actor_id,envelope FROM events WHERE event_name=%s", (name,)
    )
    assert str(row["actor_id"]) == "1"
    assert json.loads(row["envelope"])["context"]["reason"] == REASON


def test_matrix_waits_for_its_front_and_younger_walk_gets_windows_lab(world):
    hold = acquire(world, _target(NATIVE), "current")
    _queue(world, 561, "older", NATIVE)
    matrix = _queue(world, 562, "matrix", NATIVE, (NATIVE, WIN, STUDIO))

    assert active_claim(world, _target()) is None
    assert active_claim(world, _target(STUDIO)) is None
    _queue(world, 563, "younger")
    _queue(world, 564, "studio", STUDIO)
    assert active_claim(world, _target()).session_id == "younger"
    assert active_claim(world, _target(STUDIO)).session_id == "studio"

    release(world, hold.id, "closed")
    for host, waiter in ((NATIVE, "older"), (WIN, "younger"), (STUDIO, "studio")):
        taken = acquire(world, _target(host), waiter)
        release(world, taken.id, "walk passed")
    assert {row["state"] for row in execution_waits(world, matrix)} == {"reserved"}


def test_place_changes_next_turn_and_past_end_survives_requeue(world):
    hold = acquire(world, _target(), "current")
    older = _queue(world, 561, "older")
    younger = _queue(world, 562, "younger")
    _seat(world)

    last = _place(older, 999)
    assert last.primary_success, last.error
    assert last.result_payload["position"] == 2
    moved_place = execution_waits(world, older)[0]["queued_at"]
    resumed = record_host_wait(
        world, lock_plan_execution(world, older), test_machine=WIN, rationale="resume"
    )
    assert resumed["host_wait"]["position"] == 2
    assert execution_waits(world, older)[0]["queued_at"] == moved_place

    first = _place(older, 1)
    assert first.primary_success, first.error
    release(world, hold.id, "ready")
    assert active_claim(world, _target()).session_id == "older"
    assert execution_waits(world, younger)[0]["state"] == "waiting"
    _assert_event(world, "QaHostWaiterPlaced")


def test_place_returns_partial_reservations_and_keeps_the_execution_waiting(world):
    acquire(world, _target(NATIVE), "current")
    matrix = _queue(world, 561, "matrix", NATIVE, (NATIVE, WIN))
    first_partial = active_claim(world, _target())
    _queue(world, 562, "older", NATIVE)
    _queue(world, 563, "younger")
    _seat(world)

    edited = _place(matrix, 20, NATIVE)

    assert edited.primary_success, edited.error
    assert active_claim(world, _target()).session_id == "younger"
    assert active_claim(world, _target()).id != first_partial.id
    assert {row["state"] for row in execution_waits(world, matrix)} == {"waiting"}
    assert lock_plan_execution(world, matrix)["state"] == "waiting"


def test_upkeep_returns_a_partial_hold_already_behind_on_another_host(world):
    acquire(world, _target(NATIVE), "current")
    matrix = _queue(world, 561, "matrix", NATIVE, (NATIVE, WIN))
    partial = active_claim(world, _target())
    older = _queue(world, 562, "older", NATIVE)
    _queue(world, 563, "younger")
    # Seed earlier placement directly to represent a stale reservation from
    # a serving build that did not recheck the other host's line.
    world.execute(
        "UPDATE qa_test_machine_waits SET queued_at=queued_at-interval '1 hour' "
        "WHERE qa_plan_execution_id=%s",
        (older,),
    )
    world.commit()

    assert partial.id in hand_off_idle_waiter_reservations(world)
    assert active_claim(world, _target()).session_id == "younger"
    assert {row["state"] for row in execution_waits(world, matrix)} == {"waiting"}


def test_handover_preserves_the_prior_wait_and_records_the_operator(world):
    holder = _queue(world, 561, "older")
    receiver = _queue(world, 562, "younger")
    _seat(world)

    edited = _hand_over(holder, receiver)

    assert edited.primary_success, edited.error
    assert active_claim(world, _target()).session_id == "younger"
    assert lock_plan_execution(world, holder)["state"] == "waiting"
    assert execution_waits(world, holder)[0]["state"] == "waiting"
    assert execution_waits(world, receiver)[0]["state"] == "reserved"
    _assert_event(world, "QaHostTurnHandedOver")


def test_handover_refuses_receiver_behind_on_its_other_host(world):
    acquire(world, _target(NATIVE), "current")
    holder = _queue(world, 561, "older")
    _queue(world, 562, "younger", NATIVE)
    receiver = _queue(world, 563, "matrix", WIN, (WIN, NATIVE))
    _seat(world)

    refused = _hand_over(holder, receiver)

    assert refused.error.code == "qa_host_turn_receiver_blocked"
    assert active_claim(world, _target()).session_id == "older"


def test_handover_refuses_while_an_operation_borrows_the_turn(world):
    holder = _queue(world, 561, "older")
    receiver = _queue(world, 562, "younger")
    turn = active_claim(world, _target())
    borrow_turn(world, turn, "active-reset-digest")
    world.commit()
    _seat(world)

    assert _hand_over(holder, receiver).error.code == "qa_host_turn_operation_running"
    assert active_claim(world, _target()).id == turn.id


def test_queue_commands_refuse_after_custody_starts(world):
    holder = _queue(world, 561, "older")
    receiver = _queue(world, 562, "younger")
    taken = acquire(world, _target(), "older")
    world.execute(
        "UPDATE qa_plan_executions SET test_machine_lease_id=%s WHERE id=%s",
        (taken.id, holder),
    )
    world.commit()
    _seat(world)

    assert _place(holder, 1).error.code == "qa_host_turn_started"
    assert _hand_over(holder, receiver).error.code == "qa_host_turn_started"
    assert _withdraw(execution=holder).error.code == "qa_host_turn_started"
    assert active_claim(world, _target()).id == taken.id


def test_queue_edits_require_steering_authority(world):
    holder = _queue(world, 561, "older")
    receiver = _queue(world, 562, "younger")

    assert _place(receiver, 1).error.code == "steering_seat_required"
    assert _hand_over(holder, receiver).error.code == "steering_seat_required"
    assert _withdraw(execution=holder).error.code == "steering_seat_required"
    assert _withdraw(session="older", host=WIN).error.code == "steering_seat_required"
    assert active_claim(world, _target()).session_id == "older"


def test_withdraw_execution_leaves_every_line_and_passes_its_reserved_turn(world):
    acquire(world, _target(NATIVE), "current")
    holder = _queue(world, 561, "matrix", NATIVE, (NATIVE, WIN))
    receiver = _queue(world, 562, "younger")
    assert active_claim(world, _target()).session_id == "matrix"
    _seat(world)

    result = _withdraw(execution=holder)

    assert result.primary_success, result.error
    assert result.result_payload["execution_id"] == holder
    assert not execution_waits(world, holder)
    stopped = lock_plan_execution(world, holder)
    assert stopped["state"] == "aborted"
    assert stopped["release_reason"] == f"qa_host_wait_withdrawn: {REASON}"
    assert execution_waits(world, receiver)[0]["state"] == "reserved"
    world.commit()
    assert _withdraw(execution=holder).error.code == "qa_host_turn_not_waiting"


def test_withdraw_manual_wait_preserves_other_session_work(world):
    acquire(world, _target(), "current")
    walking = _queue(world, 561, "older", STUDIO)
    unrelated_lease = acquire(world, _target(STUDIO), "older")
    world.execute(
        "UPDATE qa_plan_executions SET state='active',test_machine_lease_id=%s WHERE id=%s",
        (unrelated_lease.id, walking),
    )
    wait = join_host_queue(
        world, _target(), session_id="older", actor_id=1, resume_command="manual acquire"
    )
    _queue(world, 562, "older", NATIVE)
    _seat(world)

    wrong_form = _withdraw(session="older", host=NATIVE)
    assert wrong_form.error.code == "qa_host_wait_execution_owned"
    assert "--execution" in wrong_form.error.message
    result = _withdraw(session="older", host=WIN)

    assert result.primary_success, result.error
    assert result.result_payload["wait_id"] == wait["id"]
    row = query_one(
        world, "SELECT state FROM qa_test_machine_waits WHERE id=%s", (wait["id"],)
    )
    assert row["state"] == "cancelled"
    assert active_claim(world, _target(STUDIO)).id == unrelated_lease.id
    assert active_claim(world, _target(NATIVE)).session_id == "older"
    assert lock_plan_execution(world, walking)["state"] == "active"
