"""One FIFO Test Machine line serves manual acquires and queued QA executions."""

from contextlib import nullcontext
from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.coordination_claims import (
    CoordinationClaimHeldError,
    acquire,
    active_claim,
    release,
)
from yoke_core.domain.handlers.claims_coordination_claim import handle_acquire
from yoke_core.domain.qa_host_turns import host_line, join_host_line
from yoke_core.domain.work_claim_targets import make_qa_admission_target

MACHINE = "linux-lab"
KEY = f"QA_HOST:{MACHINE}"


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


def _manual_acquire(conn, monkeypatch, session_id):
    monkeypatch.setattr(
        "yoke_core.domain.handlers.claims_coordination_claim._connect_rw",
        lambda: nullcontext(conn),
    )
    return handle_acquire(
        FunctionCallRequest(
            function="claims.coordination_claim.acquire",
            actor=ActorContext(actor_id="1", session_id=session_id),
            target=TargetRef(kind="global"),
            payload={"project_id": "1", "key": KEY, "reason": "diagnose"},
        )
    )


def _execution_wait(conn, session_id, test_machine=MACHINE):
    execution_id = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,session_id,actor_id,"
        "roster_digest,roster_json,cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,%s,'1',%s,'[]',0,'waiting',now(),now())",
        (execution_id, str(uuid4()), session_id, "a" * 64),
    )
    join_host_line(
        conn,
        make_qa_admission_target(test_machine),
        session_id=session_id,
        actor_id=1,
        resume_command="yoke qa plan run --project example --plan smoke",
        execution_id=execution_id,
    )
    conn.commit()
    return execution_id


def _wait_state(conn, session_id):
    row = conn.execute(
        "SELECT state FROM qa_host_waits WHERE session_id=%s ORDER BY queued_at DESC",
        (session_id,),
    ).fetchone()
    return row["state"]


def test_manual_and_execution_waiters_share_one_fifo_line(test_db, monkeypatch):
    seed_qa_session(test_db, "owner", "manual", "plan", "outsider")
    notices = _notices(monkeypatch)
    target = make_qa_admission_target(MACHINE)
    held = acquire(test_db, target, "owner")

    refused = _manual_acquire(test_db, monkeypatch, "manual")
    assert refused.error.code == "claim_held"
    assert "number 1 of 1 in the QA_HOST:linux-lab waiting line" in (
        refused.error.message
    )
    assert f"yoke claims coordination-claim release --claim-id {held.id}" in (
        refused.error.message
    )
    _execution_wait(test_db, "plan")
    assert [row["session_id"] for row in host_line(test_db, MACHINE)] == [
        "manual",
        "plan",
    ]

    release(test_db, held.id, "complete")
    reservation = active_claim(test_db, target)
    assert reservation.session_id == "manual"
    assert len(notices) == 1 and "yoke claims coordination-claim acquire" in notices[0]
    with pytest.raises(CoordinationClaimHeldError):
        acquire(test_db, target, "outsider")
    test_db.rollback()

    granted = _manual_acquire(test_db, monkeypatch, "manual")
    assert granted.primary_success is True
    assert granted.result_payload["claim"]["id"] == reservation.id
    assert _wait_state(test_db, "manual") == "granted"

    release(test_db, reservation.id, "diagnosed")
    assert active_claim(test_db, target).session_id == "plan"
    assert len(notices) == 2 and "requirement is still open" in notices[1]


def test_work_claim_release_by_id_advances_the_line(test_db, monkeypatch):
    from yoke_core.domain.sessions_lifecycle_claim_release import (
        release_claim_by_id,
    )

    seed_qa_session(test_db, "owner", "waiter")
    notices = _notices(monkeypatch)
    target = make_qa_admission_target(MACHINE)
    held = acquire(test_db, target, "owner")
    _manual_acquire(test_db, monkeypatch, "waiter")

    released = release_claim_by_id(test_db, held.id, "done")

    assert released["released_at"] is not None
    assert active_claim(test_db, target).session_id == "waiter"
    assert _wait_state(test_db, "waiter") == "reserved"
    assert len(notices) == 1


def test_hook_release_advances_the_line(test_db, monkeypatch):
    from yoke_core.hooks.sessions_claims import cmd_release

    seed_qa_session(test_db, "owner", "waiter")
    _notices(monkeypatch)
    target = make_qa_admission_target(MACHINE)
    held = acquire(test_db, target, "owner")
    _manual_acquire(test_db, monkeypatch, "waiter")

    cmd_release(test_db, held.id, "done")

    assert active_claim(test_db, target).session_id == "waiter"


def test_session_end_cancels_waits_and_passes_its_reserved_turn(test_db, monkeypatch):
    from yoke_core.domain.sessions_render_end import end_session

    seed_qa_session(test_db, "owner", "first", "second")
    _notices(monkeypatch)
    target = make_qa_admission_target(MACHINE)
    held = acquire(test_db, target, "owner")
    _manual_acquire(test_db, monkeypatch, "first")
    _manual_acquire(test_db, monkeypatch, "second")
    release(test_db, held.id, "complete")
    assert active_claim(test_db, target).session_id == "first"

    end_session(test_db, "first")

    assert _wait_state(test_db, "first") == "cancelled"
    assert active_claim(test_db, target).session_id == "second"
    assert _wait_state(test_db, "second") == "reserved"


def test_ended_waiter_and_other_host_do_not_block(test_db, monkeypatch):
    seed_qa_session(test_db, "ended", "other", "new")
    _notices(monkeypatch)
    _execution_wait(test_db, "ended")
    _execution_wait(test_db, "other", test_machine="other-lab")
    test_db.execute(
        "UPDATE harness_sessions SET ended_at=now() WHERE session_id=%s", ("ended",)
    )
    test_db.commit()
    claim = acquire(test_db, make_qa_admission_target(MACHINE), "new")
    assert claim.session_id == "new"


def test_cancelled_execution_passes_turn_without_double_grant(test_db, monkeypatch):
    from yoke_core.domain.qa_host_turns import cancel_host_waits, reserve_host_turn

    seed_qa_session(test_db, "first", "second")
    _notices(monkeypatch)
    first = _execution_wait(test_db, "first")
    _execution_wait(test_db, "second")
    target = make_qa_admission_target(MACHINE)
    reserve_host_turn(test_db, target)
    test_db.commit()
    cancel_host_waits(test_db, execution_ids=[first])
    test_db.commit()
    assert active_claim(test_db, target).session_id == "second"
    assert _wait_state(test_db, "first") == "cancelled"
