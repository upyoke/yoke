"""Claim-free QA ownership protects the session until resume becomes impossible."""

from __future__ import annotations

from datetime import timedelta

import pytest

from runtime.api.domain.qa_plan_execution_authority_test_support import (
    _materialize_two_cases,
)
from runtime.api.domain.session_process_liveness_report_test_support import (
    EVIDENCE,
    _apply,
    _ghost,
    _session_row,
)
from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import session_automatic_reclaim, sessions_cleanup
from yoke_core.domain.qa_plan_execution_authority import plan_execution_is_abandoned
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution, select_plan_execution
from yoke_core.domain.session_launch_store import insert_instruction_message
from yoke_core.domain.session_qa_execution_holdings import (
    session_owns_live_qa_execution,
    sessions_owning_live_qa_executions,
)
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_render_end_if_empty import end_session_if_empty
from yoke_core.domain.sessions_render_reclaim import reclaim_stale_session

OWNER = "claimless-walker"


def _begin(conn, session_id):
    return begin_plan_execution(
        conn, item_id=4909, transition_id="implemented", actor_id="1",
        session_id=session_id,
    )


@pytest.fixture
def waiting(test_db):
    _ghost(test_db, OWNER)
    _materialize_two_cases(test_db, item_id=4909)
    execution = _begin(test_db, OWNER)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='waiting' WHERE id=%s",
        (execution["id"],),
    )
    test_db.execute(
        "UPDATE harness_sessions SET mode='dash', launch_origin='yoke', "
        "executor_surface='claude-cli', executor_version=%s WHERE session_id=%s",
        (capability_for_surface("claude-cli").minimum_version, OWNER),
    )
    test_db.commit()
    return execution["id"]


def test_stop_and_reclaim_respect_live_qa(test_db, waiting):
    assert sessions_owning_live_qa_executions(test_db) == {OWNER}
    assert session_owns_live_qa_execution(test_db, OWNER)
    assert end_session_if_empty(test_db, OWNER)["status"] == "has_live_qa_execution"
    with pytest.raises(SessionError, match="yoke qa plan abort"):
        reclaim_stale_session(test_db, OWNER)
    test_db.rollback()

    test_db.execute(
        "UPDATE qa_plan_executions SET state='completed' WHERE id=%s", (waiting,)
    )
    test_db.commit()
    assert not session_owns_live_qa_execution(test_db, OWNER)
    assert end_session_if_empty(test_db, OWNER)["ended"]


@pytest.mark.parametrize("recheck", [False, True])
def test_stale_sweep_respects_live_qa(test_db, waiting, monkeypatch, recheck):
    if recheck:
        # Skip the first-pass snapshot to make the guarded recheck necessary.
        monkeypatch.setattr(
            session_automatic_reclaim, "sessions_owning_live_qa_executions", lambda _: set()
        )

    result = sessions_cleanup.clean_stale_harness_sessions(test_db, project_ids=[1])

    assert _session_row(test_db, OWNER)["ended_at"] is None
    entry = next(row for row in result["skipped_between_turns"] if row["session_id"] == OWNER)
    assert entry["reason"] == "live_qa_execution"
    assert bool(entry.get("recheck")) is recheck


def _record_failed_wake(conn, gone):
    started = gone + timedelta(seconds=1)
    insert_instruction_message(
        conn,
        message_id="resume-attempt-message", launch_id=EVIDENCE["launch_id"],
        actor_id=1, session_id=None, sender_surface=None, project_id=1,
        body="Continue the waiting QA execution", created_at=started,
        expires_at=started + timedelta(minutes=10),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id,session_id,project_id,state,resolution_evidence,routing_snapshot,created_at,wake_after) "
        "VALUES ('resume-attempt-message',%s,1,'pending','{}','{}',%s,%s)",
        (OWNER, started, started),
    )
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at,completed_at,result_code,evidence) "
        "VALUES ('resume-attempt','resume-attempt-message',%s,'wake_relay',%s,%s,'failed',%s)",
        (OWNER, started, started, '{"result_code":"transcript_missing"}'),
    )
    conn.commit()


def test_death_retains_waiting_owner_until_resume_fails_then_begin_settles(test_db, waiting):
    evidence = {**EVIDENCE, "native_exit_at": utc_now() - timedelta(minutes=2)}

    initial = _apply(test_db, OWNER, evidence=evidence)

    assert initial["skipped"] == [{"session_id": OWNER, "status": "claims_held"}]
    gone = _session_row(test_db, OWNER)["native_process_gone_at"]
    _record_failed_wake(test_db, gone)

    settled = _apply(test_db, OWNER, evidence=evidence)

    assert settled["ended"] == [OWNER]
    stranded = select_plan_execution(test_db, waiting, lock=False)
    assert plan_execution_is_abandoned(test_db, stranded)
    assert _begin(test_db, "replacement")["id"] != waiting
    assert select_plan_execution(test_db, waiting, lock=False)["state"] == "aborted"
