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


@pytest.mark.parametrize("scope", ["member", "stage", "same-session"])
def test_concurrent_stage_begins_never_duplicate_custody(test_db, monkeypatch, scope):
    run_id, members = "run-begin-concurrent", (9821, 9822)
    if scope == "member":
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
                deployment_member_item_id=members[index] if scope == "member" else None,
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
    elif scope == "member":
        assert sorted(result["state"] for result in results) == ["active", "waiting"]
        waiter = next(result for result in results if result["state"] == "waiting")
        assert waiter["shared_execution_wait"]["execution_id"] == rows[0][0]
    else:
        assert sum(isinstance(result, StageRosterHeld) for result in results) == 1


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
