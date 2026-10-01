"""Queued QA missions retain FIFO order and exclusive physical host turns."""

import json
from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_core.domain.coordination_claims import (
    acquire,
    active_claim,
    release,
    CoordinationClaimHeldError,
)
from yoke_core.domain.qa_host_turns import HOST_WAIT_KIND, queued_host_turns
from yoke_core.domain.work_claim_targets import make_qa_admission_target


def _queue(conn, session, *, when, machine="linux-lab"):
    execution_id = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,session_id,actor_id,"
        "roster_digest,roster_json,cursor_ordinal,state,created_at,heartbeat_at,release_reason) "
        "VALUES(%s,%s,%s,'2',%s,'[]',0,'waiting',%s,%s,%s)",
        (
            execution_id,
            str(uuid4()),
            session,
            "a" * 64,
            when,
            when,
            json.dumps(
                {
                    "kind": HOST_WAIT_KIND,
                    "machine": machine,
                    "queued_at": when,
                    "resume_command": "yoke qa plan run --project example --plan smoke",
                }
            ),
        ),
    )
    conn.commit()
    return execution_id


def _notices(monkeypatch):
    bodies = []

    def send(*args, **kwargs):
        bodies.append(kwargs["body"])
        return {"message_id": str(uuid4())}

    monkeypatch.setattr("yoke_core.domain.session_message_service.send_message", send)
    monkeypatch.setattr(
        "yoke_core.domain.session_explicit_wake.mark_explicit_stopped_wake",
        lambda *a, **k: None,
    )
    return bodies


def test_release_reserves_oldest_enqueue_not_oldest_plan(test_db, monkeypatch):
    seed_qa_session(test_db, "owner", "later", "first", "outsider")
    notices = _notices(monkeypatch)
    target = make_qa_admission_target("linux-lab")
    held = acquire(test_db, target, "owner")
    _queue(test_db, "later", when="2026-10-01T10:00:01Z")
    first = _queue(test_db, "first", when="2026-10-01T10:00:00Z")
    release(test_db, held.id, "complete")
    reservation = active_claim(test_db, target)
    assert reservation.session_id == "first"
    assert len(notices) == 1 and "Resume with:" in notices[0]
    with pytest.raises(CoordinationClaimHeldError):
        acquire(test_db, target, "outsider")
    test_db.rollback()
    consumed = acquire(test_db, target, "first", reason="machine-qa-execution")
    assert consumed.id == reservation.id
    assert all(row["id"] != first for row in queued_host_turns(test_db, "linux-lab"))
    release(test_db, consumed.id, "complete")
    assert active_claim(test_db, target).session_id == "later"
    assert len(notices) == 2


def test_ended_waiter_and_other_host_do_not_block(test_db, monkeypatch):
    seed_qa_session(test_db, "ended", "other", "new")
    _notices(monkeypatch)
    _queue(test_db, "ended", when="2026-10-01T10:00:00Z")
    _queue(test_db, "other", when="2026-10-01T10:00:01Z", machine="other-lab")
    test_db.execute(
        "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
        ("2026-10-01T10:01:00Z", "ended"),
    )
    test_db.commit()
    claim = acquire(test_db, make_qa_admission_target("linux-lab"), "new")
    assert claim.session_id == "new"


def test_cancelled_reservation_passes_turn_without_double_grant(test_db, monkeypatch):
    from yoke_core.domain.qa_host_turns import release_host_reservations

    seed_qa_session(test_db, "first", "second")
    _notices(monkeypatch)
    first = _queue(test_db, "first", when="2026-10-01T10:00:00Z")
    _queue(test_db, "second", when="2026-10-01T10:00:01Z")
    target = make_qa_admission_target("linux-lab")
    from yoke_core.domain.qa_host_turns import reserve_host_turn

    reserve_host_turn(test_db, target)
    test_db.commit()
    release_host_reservations(test_db, first)
    test_db.commit()
    assert active_claim(test_db, target).session_id == "second"
