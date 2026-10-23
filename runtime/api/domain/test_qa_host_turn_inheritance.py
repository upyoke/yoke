"""A recovery walk of an aborted shared walk resumes next on its host."""

from datetime import timedelta
from uuid import uuid4

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_host_turn_inheritance import inherited_host_place
from yoke_core.domain.qa_host_turns import host_line, join_host_line, record_host_wait
from yoke_core.domain.work_claim_targets import make_qa_admission_target

MACHINE = "test-mac"
RUN = "run-20261021-006"


def _quiet(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.session_message_service.send_message",
        lambda *a, **k: {"message_id": str(uuid4())},
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_explicit_wake.mark_explicit_stopped_wake",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_continuation.continuation_recipe",
        lambda conn, execution: "yoke qa plan run --deployment-run " + RUN,
    )


def _execution(conn, session_id, *, created_at, stage="item-qa", member=None):
    execution_id = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,session_id,actor_id,roster_digest,roster_json,"
        "cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,%s,%s,%s,'1',%s,'[]',0,'active',%s,%s)",
        (execution_id, RUN, stage, member, session_id, "a" * 64, created_at, created_at),
    )
    return execution_id


def _row(conn, execution_id):
    row = query_one(
        conn, "SELECT * FROM qa_plan_executions WHERE id=%s", (execution_id,)
    )
    return {**row, "roster": []}


def _aborted_walk(conn, monkeypatch, **shape):
    """The owner walks the host, two sessions queue behind it, then it aborts."""
    seed_qa_session(conn, "owner", "first", "second", "holder")
    _quiet(monkeypatch)
    target = make_qa_admission_target(MACHINE)
    prior = _execution(conn, "owner", created_at=utc_now() - timedelta(hours=2), **shape)
    lease = acquire(conn, target, "owner")
    for waiter in ("first", "second"):
        join_host_line(
            conn, target, session_id=waiter, actor_id=1, resume_command="yoke acquire"
        )
    release(conn, lease.id, "aborted")
    conn.execute(
        "UPDATE qa_plan_executions SET state='aborted',completed_at=%s WHERE id=%s",
        (utc_now(), prior),
    )
    conn.commit()
    return _execution(conn, "owner", created_at=utc_now(), **shape)


def test_recovery_walk_resumes_next_ahead_of_unrelated_waiters(test_db, monkeypatch):
    recovery = _aborted_walk(test_db, monkeypatch)
    target = make_qa_admission_target(MACHINE)
    first_turn = active_claim(test_db, target)
    assert first_turn.session_id == "first"

    waiting = record_host_wait(
        test_db, _row(test_db, recovery), test_machine=MACHINE, rationale="host busy"
    )

    assert waiting["host_wait"]["position"] == 1
    assert [row["session_id"] for row in host_line(test_db, MACHINE)] == [
        "owner",
        "second",
    ]
    release(test_db, first_turn.id, "done")
    assert active_claim(test_db, target).session_id == "owner"


def test_member_walk_and_other_stage_keep_fifo(test_db, monkeypatch):
    member = _aborted_walk(test_db, monkeypatch, member=4233)
    assert inherited_host_place(test_db, _row(test_db, member), MACHINE) is None
    other = _execution(test_db, "owner", created_at=utc_now(), stage="release-qa")
    assert inherited_host_place(test_db, _row(test_db, other), MACHINE) is None


def test_walk_that_already_held_the_host_keeps_fifo(test_db, monkeypatch):
    recovery = _aborted_walk(test_db, monkeypatch)
    row = _row(test_db, recovery)
    assert inherited_host_place(test_db, row, MACHINE) is not None
    target = make_qa_admission_target(MACHINE)
    release(test_db, active_claim(test_db, target).id, "done")
    release(test_db, active_claim(test_db, target).id, "done")
    release(test_db, acquire(test_db, target, "owner").id, "case done")
    assert inherited_host_place(test_db, row, MACHINE) is None
