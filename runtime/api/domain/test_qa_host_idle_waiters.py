"""An away set-waiter's partial reservations go to the next waiter (YOK-5511).

The measured miss, again after the first fix shipped: session b324a065, parked
with its process gone, kept reserved turns on three lab hosts for hours while
it waited for a fourth that a live session held, and younger waiters on those
hosts could not start.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import _execution_wait, _notices
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.coordination_claims import acquire, active_claim, get_claim, release
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_host_idle_hold import IDLE_HOLD_RESERVATION_REASON
from yoke_core.domain.qa_host_idle_waiters import hand_off_idle_waiter_reservations
from yoke_core.domain.qa_host_set_turns import record_host_wait
from yoke_core.domain.work_claim_targets import make_qa_admission_target

A, B = "lab-a", "lab-b"


def _target(name):
    return make_qa_admission_target(name)


def _set_waiter(conn, session_id):
    """*session_id*'s execution waits on A (held) with B reserved for it."""
    execution_id = _execution_wait(conn, session_id, test_machine=A)
    execution = query_one(conn, "SELECT * FROM qa_plan_executions WHERE id=%s", (execution_id,))
    record_host_wait(
        conn, {**execution, "roster": []}, test_machine=A, rationale="busy",
        test_machines=(A, B),
    )
    return execution_id


def _waits(conn, execution_id):
    return conn.execute(
        "SELECT test_machine,state,queued_at FROM qa_test_machine_waits "
        "WHERE qa_plan_execution_id=%s AND state IN ('waiting','reserved') "
        "ORDER BY test_machine",
        (execution_id,),
    ).fetchall()


def _away(conn, session_id, *, idle=timedelta(days=2)):
    conn.execute(
        "UPDATE harness_sessions SET mode='parked',quiet_reason='HUMAN_GATE',"
        "last_tool_call_at=%s,native_process_gone_at=%s WHERE session_id=%s",
        (utc_now() - idle, utc_now() - idle, session_id),
    )
    conn.commit()


def test_away_set_waiter_hands_its_partial_reservation_to_the_next_waiter(
    test_db, monkeypatch
):
    bodies = _notices(monkeypatch)
    seed_qa_session(test_db, "holder-a", "away", "younger")
    acquire(test_db, _target(A), "holder-a")
    away = _set_waiter(test_db, "away")
    partial = active_claim(test_db, _target(B))
    assert partial.session_id == "away"
    younger = _execution_wait(test_db, "younger", test_machine=B)
    before = _waits(test_db, away)
    # Inside the limit the reservation stays with its set.
    assert hand_off_idle_waiter_reservations(test_db) == []
    _away(test_db, "away")

    assert hand_off_idle_waiter_reservations(test_db) == [partial.id]

    assert not get_claim(test_db, partial.id).is_active
    intent = query_one(
        test_db, "SELECT release_reason_intent FROM work_claims WHERE id=%s", (partial.id,)
    )
    assert intent["release_reason_intent"] == IDLE_HOLD_RESERVATION_REASON
    taken = active_claim(test_db, _target(B))
    assert taken.session_id == "younger"
    assert len(bodies) == 1 and f"QA host turn ready: {B}" in bodies[0]
    # The away waiter keeps its one place on both hosts.
    after = _waits(test_db, away)
    assert [(r[0], r[1]) for r in after] == [(A, "waiting"), (B, "waiting")]
    assert {r[2] for r in after} == {before[0][2]}
    assert query_one(
        test_db, "SELECT state FROM qa_plan_executions WHERE id=%s", (younger,)
    )["state"] == "waiting"


def test_returning_waiter_is_served_again_at_its_place(test_db, monkeypatch):
    _notices(monkeypatch)
    seed_qa_session(test_db, "holder-a", "away", "younger")
    held_a = acquire(test_db, _target(A), "holder-a")
    away = _set_waiter(test_db, "away")
    _execution_wait(test_db, "younger", test_machine=B)
    _away(test_db, "away")
    hand_off_idle_waiter_reservations(test_db)
    younger_turn = active_claim(test_db, _target(B))
    assert younger_turn.session_id == "younger"

    # Away, it is passed over for A too: a lone host would only strand.
    release(test_db, held_a.id, "done")
    assert active_claim(test_db, _target(A)) is None

    # Its next tool call ends the skip; B's next release serves it first.
    test_db.execute(
        "UPDATE harness_sessions SET mode='wait',native_process_gone_at=NULL,"
        "last_tool_call_at=%s WHERE session_id='away'",
        (utc_now(),),
    )
    test_db.commit()
    taken = acquire(test_db, _target(B), "younger")
    assert taken.id == younger_turn.id
    release(test_db, taken.id, "case done")
    assert active_claim(test_db, _target(B)).session_id == "away"
    assert [r[1] for r in _waits(test_db, away)] == ["waiting", "reserved"]


def test_a_woken_set_waiter_keeps_its_reservation_before_a_tool_completes(
    test_db, monkeypatch,
):
    _notices(monkeypatch)
    seed_qa_session(test_db, "holder-a", "waiter")
    acquire(test_db, _target(A), "holder-a")
    execution_id = _set_waiter(test_db, "waiter")
    death = utc_now() - timedelta(hours=2)
    test_db.execute(
        "UPDATE harness_sessions SET mode='wait', last_tool_call_at=%s, "
        "native_process_gone_at=%s, turn_posture='running', turn_posture_at=%s "
        "WHERE session_id='waiter'",
        (death, death, utc_now()),
    )
    test_db.commit()
    assert hand_off_idle_waiter_reservations(test_db) == []
    assert active_claim(test_db, _target(B)).session_id == "waiter"
    assert [r[1] for r in _waits(test_db, execution_id)] == ["waiting", "reserved"]


def test_a_live_parked_set_waiter_keeps_its_reservation(test_db, monkeypatch):
    _notices(monkeypatch)
    seed_qa_session(test_db, "holder-a", "waiter")
    acquire(test_db, _target(A), "holder-a")
    _set_waiter(test_db, "waiter")
    test_db.execute(
        "UPDATE harness_sessions SET mode='parked',last_tool_call_at=%s "
        "WHERE session_id='waiter'",
        (utc_now() - timedelta(minutes=5),),
    )
    test_db.commit()
    assert hand_off_idle_waiter_reservations(test_db) == []
    assert active_claim(test_db, _target(B)).session_id == "waiter"


@pytest.mark.parametrize(
    ("surface", "origin", "resumable"),
    [("claude-cli", "yoke", True), ("codex-desktop", "yoke", False), ("claude-cli", "operator", False)],
)
def test_stopped_set_waiter_is_served_only_if_yoke_can_resume(
    test_db, monkeypatch, surface, origin, resumable,
):
    _notices(monkeypatch)
    seed_qa_session(test_db, "holder", "walker")
    holder = acquire(test_db, _target(A), "holder")
    execution = _set_waiter(test_db, "walker")
    test_db.execute(
        "UPDATE harness_sessions SET executor_surface=%s, launch_origin=%s "
        "WHERE session_id='walker'",
        (surface, origin),
    )
    _away(test_db, "walker", idle=timedelta(hours=2))

    partial = active_claim(test_db, _target(B))
    assert hand_off_idle_waiter_reservations(test_db) == ([] if resumable else [partial.id])
    if not resumable:
        assert not get_claim(test_db, partial.id).is_active
        return
    assert active_claim(test_db, _target(B)).session_id == "walker"

    release(test_db, holder.id, "finished")

    assert [(row[0], row[1]) for row in _waits(test_db, execution)] == [
        (A, "reserved"), (B, "reserved"),
    ]
