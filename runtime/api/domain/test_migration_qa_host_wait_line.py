"""The history entry moves queued executions into the Test Machine line."""

from __future__ import annotations

import importlib
import json
from uuid import uuid4

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_core.domain.coordination_claims import acquire
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.work_claim_targets import make_qa_admission_target

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0075_qa_host_wait_line"
)


def _queued(conn, session_id, *, state, machine="linux-lab", queued_at):
    execution_id = str(uuid4())
    wait = {
        "kind": "qa_host_wait",
        "machine": machine,
        "queued_at": queued_at,
        "rationale": "lease held",
        "resume_command": f"resume {session_id}",
    }
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,session_id,actor_id,"
        "roster_digest,roster_json,cursor_ordinal,state,created_at,heartbeat_at,"
        "release_reason) VALUES(%s,%s,%s,'1',%s,'[]',0,%s,now(),now(),%s)",
        (execution_id, str(uuid4()), session_id, "a" * 64, state, json.dumps(wait)),
    )
    return execution_id


def _waits(conn):
    return {
        row["session_id"]: dict(row)
        for row in conn.execute(
            "SELECT session_id,state,claim_id,queued_at,resume_command,"
            "qa_plan_execution_id FROM qa_host_waits"
        ).fetchall()
    }


def test_entry_moves_waiting_and_reserved_executions_into_the_line(test_db):
    # The entry creates its retired line table in its own shape; the
    # current schema keeps the line in a later table.
    assert test_db.execute(
        "SELECT to_regclass('qa_host_waits')"
    ).fetchone()[0] is None
    seed_qa_session(test_db, "waiter", "reserved", "settled")
    waiting = _queued(
        test_db, "waiter", state="waiting", queued_at="2026-10-01T10:00:01Z"
    )
    turn = _queued(
        test_db, "reserved", state="active", queued_at="2026-10-01T10:00:00Z"
    )
    claim = acquire(
        test_db,
        make_qa_admission_target("linux-lab"),
        "reserved",
        reason="qa-host-turn:" + turn,
        commit=False,
    )
    settled = _queued(
        test_db, "settled", state="aborted", queued_at="2026-10-01T09:00:00Z"
    )

    MIGRATION.apply(test_db)
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)

    waits = _waits(test_db)
    assert set(waits) == {"waiter", "reserved"}
    assert waits["waiter"]["state"] == "waiting"
    assert waits["waiter"]["qa_plan_execution_id"] == waiting
    assert waits["waiter"]["resume_command"] == "resume waiter"
    assert waits["reserved"]["state"] == "reserved"
    assert waits["reserved"]["claim_id"] == claim.id
    reasons = dict(
        test_db.execute(
            "SELECT id,release_reason FROM qa_plan_executions WHERE id IN (%s,%s,%s)",
            (waiting, turn, settled),
        ).fetchall()
    )
    assert reasons == {
        waiting: "waiting for QA host linux-lab",
        turn: None,
        settled: None,
    }


def test_entry_declares_the_next_release_serving_floor():
    assert MIGRATION.MINIMUM_SERVING_VERSION == NEXT_RELEASE
