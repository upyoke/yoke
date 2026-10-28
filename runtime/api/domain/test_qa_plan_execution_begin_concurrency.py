"""Run-locked admission converges without fingerprinting execution churn."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from runtime.api.domain.test_qa_plan_execution_begin_lock_window import (
    LockWindowRecorder,
    _seed,
    _seed_stage_wide,
    _stage_wide_begin,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain import qa_plan_execution_begin_admission as admission
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_stage_execution_holders import StageRosterHeld


@pytest.mark.parametrize("scope", ["plan-group", "stage", "same-session"])
def test_concurrent_stage_begins_never_duplicate_custody(test_db, monkeypatch, scope):
    run_id, members = "run-begin-concurrent", (9821, 9822)
    if scope == "plan-group":
        _seed(test_db, run_id, members)
    else:
        _seed_stage_wide(test_db, run_id, members)
    connections = [connect_test_database(test_db.info.dbname) for _ in members]
    barrier = Barrier(2)
    admit = admission.admit_member

    def simultaneous_admit(*args, **kwargs):
        barrier.wait(timeout=20)
        return admit(*args, **kwargs)

    def begin(index):
        try:
            return begin_plan_execution(
                connections[index],
                deployment_run_id=run_id,
                deployment_stage="item-qa",
                deployment_member_item_id=members[index] if scope == "plan-group" else None,
                plan=f"shared-{run_id}" if scope == "plan-group" else None,
                actor_id="2",
                session_id="same-session" if scope == "same-session" else f"racer-{index}",
            )
        except StageRosterHeld as exc:
            return exc
        finally:
            connections[index].rollback()

    monkeypatch.setattr(admission, "admit_member", simultaneous_admit)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(begin, range(2)))
    finally:
        for conn in connections:
            conn.close()
    rows = test_db.execute(
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s", (run_id,)
    ).fetchall()
    assert len(rows) == 1, results
    if scope == "same-session":
        assert {result["id"] for result in results} == {rows[0][0]}
    else:
        held = [result for result in results if isinstance(result, StageRosterHeld)]
        assert len(held) == 1, results
        assert held[0].execution["id"] == rows[0][0]


def test_execution_churn_does_not_repeat_the_roster_read(test_db, monkeypatch):
    from yoke_core.domain import qa_plan_execution_begin as beginning
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    run_id, members = "run-begin-execution-churn", (9831, 9832)
    _seed_stage_wide(test_db, run_id, members)
    other = connect_test_database(test_db.info.dbname)
    admit, prepare = admission.admit_member, beginning.prepare_roster
    reads, raced = [], []

    def recorded_prepare(*args, **kwargs):
        reads.append(True)
        return prepare(*args, **kwargs)

    def churn_then_admit(*args, **kwargs):
        if not raced:
            raced.append(True)
            execution = _stage_wide_begin(other, run_id, session="short-lived")
            finish_plan_execution(other, execution, state="aborted", reason="finished")
        return admit(*args, **kwargs)

    monkeypatch.setattr(admission, "admit_member", churn_then_admit)
    monkeypatch.setattr(beginning, "prepare_roster", recorded_prepare)
    recorder = LockWindowRecorder(test_db)
    try:
        result = _stage_wide_begin(recorder, run_id)
    finally:
        other.close()
    assert result["state"] == "active"
    assert len(reads) == 2  # One preparation for each begin, with no retry.
    assert not any("string_agg(id||" in sql for sql in recorder.log)


def test_retirement_rechecks_custody_after_reacquiring_the_run_lock(test_db, monkeypatch):
    from yoke_core.domain import qa_plan_execution_begin as beginning
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    run_id, members = "run-begin-retirement-race", (9841, 9842)
    _seed_stage_wide(test_db, run_id, members)
    first = _stage_wide_begin(test_db, run_id)
    other = connect_test_database(test_db.info.dbname)
    admit = admission.admit_member
    retired, raced = [], []

    def retire(conn, execution, *, digest):
        finish_plan_execution(conn, execution, state="aborted", reason="changed-roster")
        retired.append(True)
        return True

    def race_after_retirement(*args, **kwargs):
        if retired and not raced:
            raced.append({})
            raced[0] = _stage_wide_begin(other, run_id, session="retirement-racer")
        return admit(*args, **kwargs)

    monkeypatch.setattr(beginning, "retire_unstarted_changed_roster", retire)
    monkeypatch.setattr(admission, "admit_member", race_after_retirement)
    try:
        with pytest.raises(StageRosterHeld) as held:
            _stage_wide_begin(test_db, run_id)
        assert held.value.execution["id"] == raced[0]["id"]
        assert held.value.execution["id"] != first["id"]
    finally:
        test_db.rollback()
        other.close()
    rows = test_db.execute(
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s AND state='active'",
        (run_id,),
    ).fetchall()
    assert [row[0] for row in rows] == [raced[0]["id"]]


def test_admission_checks_owner_lifetime_with_the_execution_locked(test_db, monkeypatch):
    import psycopg

    from yoke_core.domain import qa_plan_execution_authority as authority
    from yoke_core.domain.qa_stage_execution_holders import admit_stage_roster

    run_id, members = "run-begin-owner-lifetime", (9851, 9852)
    _seed_stage_wide(test_db, run_id, members)
    owner = _stage_wide_begin(test_db, run_id, session="live-owner")
    probe = connect_test_database(test_db.info.dbname)
    checked = []

    def live_owner(conn, execution):
        with pytest.raises(psycopg.errors.LockNotAvailable):
            probe.execute(
                "SELECT id FROM qa_plan_executions WHERE id=%s FOR UPDATE NOWAIT",
                (execution["id"],),
            )
        probe.rollback()
        checked.append(execution["id"])
        return False

    monkeypatch.setattr(authority, "plan_execution_is_abandoned", live_owner)
    try:
        with pytest.raises(StageRosterHeld):
            admit_stage_roster(
                test_db, owner["roster"], deployment_run_id=run_id,
                deployment_stage="item-qa", session_id="competing-owner",
            )
    finally:
        test_db.rollback()
        probe.close()
    assert checked == [owner["id"]]
