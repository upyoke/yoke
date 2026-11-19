"""A session that just used a Test Machine keeps a short same-session hold-over.

Measured misses: YOK-5459 took test-mac-studio (lease 51833) 0.22s after
YOK-5475's last ``yoke test-machine exec`` preflight released it, before
YOK-5475's ``qa case run`` queued; and YOK-5475's reserved turn (lease 51842)
went to YOK-5459 (lease 51843) when YOK-5475 aborted its execution refused
``served_build_changed`` after a deploy.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import (
    MACHINE,
    _execution_wait,
    _notices,
)
from yoke_core.domain.coordination_claims import (
    CoordinationClaimHeldError,
    acquire,
    active_claim,
    release,
)
from yoke_core.domain.qa_host_holdover import (
    DIRECT_OPERATION_REASON,
    HOLDOVER_REASON,
    OWNER_ABORT,
    expire_holdovers,
    holdover_wait,
    session_holdovers,
)
from yoke_core.domain.qa_host_set_turns import require_host_set_turn
from yoke_core.domain.qa_host_turns import host_line, join_host_line, reserve_host_turn
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution, roster_digest
from yoke_core.domain.work_claim_targets import make_qa_admission_target

TARGET = make_qa_admission_target(MACHINE)
CASE_RUN = "machine-qa-execution"


def _preflight(conn, session_id):
    """One direct operation: take the host's lease, run, release it."""
    lease = acquire(conn, TARGET, session_id, reason=DIRECT_OPERATION_REASON)
    release(conn, lease.id, "finished: test-machine exec")
    conn.commit()
    return lease


def _lapse(conn, claim_id):
    conn.execute(
        "UPDATE work_claims SET last_heartbeat=now() - interval '121 seconds' WHERE id=%s",
        (claim_id,),
    )
    conn.commit()


def _waits(conn, session_id):
    return [
        (row["state"], row["qa_plan_execution_id"])
        for row in conn.execute(
            "SELECT state,qa_plan_execution_id FROM qa_test_machine_waits "
            "WHERE session_id=%s ORDER BY queued_at,id",
            (session_id,),
        ).fetchall()
    ]


def test_preflight_then_case_run_within_ttl_beats_another_sessions_run(
    test_db, monkeypatch
):
    seed_qa_session(test_db, "preflighter", "walker")
    _notices(monkeypatch)
    _preflight(test_db, "preflighter")

    holdover = active_claim(test_db, TARGET)
    assert holdover.session_id == "preflighter"
    assert holdover.reason == HOLDOVER_REASON
    assert session_holdovers(test_db, "preflighter")[0]["claim_id"] == holdover.id

    # Another session's plan run inside the TTL is refused and queues behind it.
    with pytest.raises(CoordinationClaimHeldError):
        acquire(test_db, TARGET, "walker", reason=CASE_RUN)
    test_db.rollback()
    _execution_wait(test_db, "walker")

    # Repeated preflights consume and renew the hold-over.
    again = _preflight(test_db, "preflighter")
    assert again.id == holdover.id
    renewed = active_claim(test_db, TARGET)
    assert renewed.session_id == "preflighter" and renewed.id != holdover.id

    lease = acquire(test_db, TARGET, "preflighter", reason=CASE_RUN)
    assert lease.id == renewed.id
    assert holdover_wait(test_db, active_claim(test_db, TARGET)) is None
    assert [row["session_id"] for row in host_line(test_db, MACHINE)] == ["walker"]

    # The case run's own release is no direct operation: the line is served.
    release(test_db, lease.id, "case complete")
    assert active_claim(test_db, TARGET).session_id == "walker"


def test_after_the_ttl_another_session_acquires(test_db, monkeypatch):
    seed_qa_session(test_db, "preflighter", "walker")
    _notices(monkeypatch)
    _preflight(test_db, "preflighter")
    _lapse(test_db, active_claim(test_db, TARGET).id)

    lease = acquire(test_db, TARGET, "walker", reason=CASE_RUN)

    assert lease.session_id == "walker"
    assert session_holdovers(test_db, "preflighter") == []
    assert [state for state, _ in _waits(test_db, "preflighter")] == ["cancelled"]


def test_upkeep_releases_a_lapsed_holdover_to_the_queued_waiter(test_db, monkeypatch):
    seed_qa_session(test_db, "preflighter", "walker")
    notices = _notices(monkeypatch)
    _preflight(test_db, "preflighter")
    _execution_wait(test_db, "walker")
    holdover = active_claim(test_db, TARGET)

    assert expire_holdovers(test_db) == []
    _lapse(test_db, holdover.id)
    assert expire_holdovers(test_db) == [holdover.id]

    assert active_claim(test_db, TARGET).session_id == "walker"
    assert len(notices) == 1 and f"QA host turn ready: {MACHINE}" in notices[0]


def test_an_already_queued_waiter_beats_the_holdover(test_db, monkeypatch):
    seed_qa_session(test_db, "preflighter", "walker")
    _notices(monkeypatch)
    lease = acquire(test_db, TARGET, "preflighter", reason=DIRECT_OPERATION_REASON)
    _execution_wait(test_db, "walker")

    release(test_db, lease.id, "finished: test-machine exec")

    assert active_claim(test_db, TARGET).session_id == "walker"
    assert session_holdovers(test_db, "preflighter") == []
    with pytest.raises(CoordinationClaimHeldError):
        acquire(test_db, TARGET, "preflighter", reason=CASE_RUN)


def test_an_ended_session_leaves_no_holdover(test_db, monkeypatch):
    seed_qa_session(test_db, "preflighter")
    _notices(monkeypatch)
    lease = acquire(test_db, TARGET, "preflighter", reason=DIRECT_OPERATION_REASON)
    test_db.execute(
        "UPDATE harness_sessions SET ended_at=now() WHERE session_id='preflighter'"
    )

    release(test_db, lease.id, "finished: test-machine exec")

    assert active_claim(test_db, TARGET) is None


def _queued_execution(conn, session_id):
    execution_id = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,session_id,actor_id,"
        "roster_digest,roster_json,cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,%s,'1',%s,'[]',0,'waiting',now(),now())",
        (execution_id, str(uuid4()), session_id, roster_digest([])),
    )
    join_host_line(
        conn, TARGET, session_id=session_id, actor_id=1,
        resume_command="unused for plan executions", execution_id=execution_id,
    )
    conn.commit()
    return execution_id


def _reserved_for_first(conn, monkeypatch):
    seed_qa_session(conn, "owner", "rerunner", "walker")
    _notices(monkeypatch)
    held = acquire(conn, TARGET, "owner")
    stale = _queued_execution(conn, "rerunner")
    _queued_execution(conn, "walker")
    release(conn, held.id, "done")
    reservation = active_claim(conn, TARGET)
    assert reservation.session_id == "rerunner"
    return lock_plan_execution(conn, stale), reservation


def test_owner_abort_carries_its_reserved_turn_to_its_next_execution(
    test_db, monkeypatch
):
    stale, reservation = _reserved_for_first(test_db, monkeypatch)
    stale[OWNER_ABORT] = True

    finish_plan_execution(
        test_db, stale, state="aborted", reason="served_build_changed; rerunning"
    )

    assert active_claim(test_db, TARGET).id == reservation.id
    assert session_holdovers(test_db, "rerunner")[0]["claim_id"] == reservation.id
    assert [row["session_id"] for row in host_line(test_db, MACHINE)] == ["walker"]
    with pytest.raises(CoordinationClaimHeldError):
        acquire(test_db, TARGET, "walker", reason=CASE_RUN)
    test_db.rollback()

    rerun = lock_plan_execution(test_db, _queued_execution(test_db, "rerunner"))
    reserve_host_turn(test_db, TARGET)
    require_host_set_turn(test_db, rerun, (MACHINE,))
    lease = acquire(test_db, TARGET, "rerunner", reason=CASE_RUN)
    assert lease.id == reservation.id


def test_an_abort_its_owner_did_not_ask_for_serves_the_line(test_db, monkeypatch):
    stale, _ = _reserved_for_first(test_db, monkeypatch)

    finish_plan_execution(test_db, stale, state="aborted", reason="steering stop")

    assert active_claim(test_db, TARGET).session_id == "walker"
    assert session_holdovers(test_db, "rerunner") == []
