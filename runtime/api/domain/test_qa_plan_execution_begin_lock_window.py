"""Beginning a plan group's QA walk holds the run row lock only to write.

Every per-member read happens before ``deployment_runs`` is locked, so the
statements issued while the lock is held stay the same whether the run has
three members or thirty, and a change committed between that read and the
lock is still honoured.
"""

from __future__ import annotations

from runtime.api.domain.qa_plan_execution_begin_lock_window_test_support import (
    LockWindowRecorder as LockWindowRecorder,
    _seed as _seed,
    _seed_stage_wide as _seed_stage_wide,
    _stage_wide_begin as _stage_wide_begin,
)


from collections import Counter

import pytest

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_stage_execution_holders import StageRosterHeld

SMALL = ("run-begin-lock-small", tuple(range(9601, 9604)))
LARGE = ("run-begin-lock-large", tuple(range(9701, 9731)))


def _begin(conn, run_id, member, session="begin-lock-window"):
    """Begin the run's plan group; ``member`` only records who asked."""
    return begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        plan=f"shared-{run_id}",
        actor_id="2",
        session_id=session,
    )


def _locked_statements(conn, run_id, members):
    _seed(conn, run_id, members)
    recorder = LockWindowRecorder(conn)
    execution = _begin(recorder, run_id, members[1])
    assert execution["deployment_member_item_id"] is None
    assert execution["requesting_member_item_id"] == members[1]
    return recorder.locked()


def test_statements_under_the_run_lock_do_not_grow_with_members(test_db):
    small = _locked_statements(test_db, *SMALL)
    large = _locked_statements(test_db, *LARGE)
    assert small, "beginning the execution must still lock the run to write"
    grown = Counter(large) - Counter(small)
    assert len(large) == len(small), "\n".join(
        f"{count} more: {statement[:160]}" for statement, count in grown.items()
    )


def test_an_execution_begun_between_read_and_lock_is_honoured(test_db, monkeypatch):
    from runtime.api.fixtures.pg_testdb import connect_test_database
    from yoke_core.domain import qa_plan_execution_begin_admission as admission

    run_id, members = SMALL
    _seed(test_db, run_id, members)
    admit = admission.admit_member
    other = connect_test_database(test_db.info.dbname)
    raced: list[dict] = []

    def begin_elsewhere_then_admit(*args, **kwargs):
        if not raced:
            raced.append({})
            raced[0] = _begin(other, run_id, members[0], session="other-session")
        return admit(*args, **kwargs)

    monkeypatch.setattr(admission, "admit_member", begin_elsewhere_then_admit)
    try:
        with pytest.raises(StageRosterHeld) as held:
            _begin(test_db, run_id, members[1])
        test_db.rollback()
    finally:
        other.close()
    assert raced and raced[0]["session_id"] == "other-session"
    assert held.value.execution["id"] == raced[0]["id"]
    assert held.value.execution["session_id"] == "other-session"
    assert "park" in str(held.value)
    rows = test_db.execute(
        "SELECT session_id FROM qa_plan_executions WHERE deployment_run_id=%s",
        (run_id,),
    ).fetchall()
    assert [row[0] for row in rows] == ["other-session"]


def test_a_group_begin_reads_again_unlocked_then_refuses_by_name(
    test_db, monkeypatch
):
    """Each re-read runs unlocked; a run that keeps changing refuses by name."""
    from yoke_core.domain.deployment_runs_lock import (
        RUN_BUSY_CODE,
        RUN_READ_ATTEMPTS,
        DeploymentRunChanging,
    )

    run_id, members = SMALL
    _seed(test_db, run_id, members)
    probe, reads, locked = _record_roster_reads(
        test_db, monkeypatch, run_id, [False] * RUN_READ_ATTEMPTS
    )
    try:
        with pytest.raises(DeploymentRunChanging) as raised:
            _begin(test_db, run_id, members[1])
        assert not locked()
    finally:
        probe.close()
    assert reads == [False] * RUN_READ_ATTEMPTS
    assert str(raised.value).startswith(f"{RUN_BUSY_CODE}: deployment run {run_id!r}")
    assert "(run_read_changed)" in str(raised.value)
    assert not test_db.execute(
        "SELECT 1 FROM qa_plan_executions WHERE deployment_run_id=%s", (run_id,)
    ).fetchone()


STAGE_WIDE = ("run-begin-lock-stage-wide", tuple(range(9801, 9803)))


def _record_roster_reads(test_db, monkeypatch, run_id, admits):
    """Record whether the run row was locked at each roster read.

    Each admit answers the next scripted entry of ``admits`` (stale when
    ``False``) after taking its locks, then the real answer once it is empty.
    """
    import psycopg

    from runtime.api.fixtures.pg_testdb import connect_test_database
    from yoke_core.domain import qa_plan_execution_begin_admission as admission

    probe = connect_test_database(test_db.info.dbname)
    admit, prepare = admission.admit_member, admission.prepare_roster
    reads: list[bool] = []

    def locked() -> bool:
        try:
            probe.execute(
                "SELECT 1 FROM deployment_runs WHERE id=%s FOR UPDATE NOWAIT",
                (run_id,),
            )
            return False
        except psycopg.errors.LockNotAvailable:
            return True
        finally:
            probe.rollback()

    def recorded_prepare(*args, **kwargs):
        reads.append(locked())
        return prepare(*args, **kwargs)

    def scripted_admit(*args, **kwargs):
        held = admit(*args, **kwargs)
        return held and (admits.pop(0) if admits else True)

    monkeypatch.setattr(admission, "admit_member", scripted_admit)
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_begin.prepare_roster", recorded_prepare
    )
    return probe, reads, locked


def test_a_stage_wide_begin_reads_again_unlocked_then_refuses_by_name(
    test_db, monkeypatch
):
    from yoke_core.domain.deployment_runs_lock import (
        RUN_BUSY_CODE,
        RUN_READ_ATTEMPTS,
        DeploymentRunChanging,
    )

    run_id, members = STAGE_WIDE
    _seed_stage_wide(test_db, run_id, members)
    probe, reads, locked = _record_roster_reads(
        test_db, monkeypatch, run_id, admits := [False]
    )
    try:
        execution = _stage_wide_begin(test_db, run_id)
        assert reads == [False, False]  # stale once, read again unlocked
        assert execution["session_id"] == "begin-lock-window"
        reads.clear()
        test_db.execute(
            "DELETE FROM qa_plan_executions WHERE deployment_run_id=%s", (run_id,)
        )
        test_db.commit()
        admits[:] = [False] * RUN_READ_ATTEMPTS
        with pytest.raises(DeploymentRunChanging) as raised:
            _stage_wide_begin(test_db, run_id, session="begin-lock-churn")
        assert not locked()
    finally:
        probe.close()
    assert reads == [False] * RUN_READ_ATTEMPTS
    assert str(raised.value).startswith(f"{RUN_BUSY_CODE}: deployment run {run_id!r}")
    assert "(run_read_changed)" in str(raised.value)


def test_a_begin_that_retired_an_execution_reads_again_unlocked(
    test_db, monkeypatch
):
    from yoke_core.domain import qa_plan_execution_begin
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    run_id, members = ("run-begin-lock-retired", tuple(range(9811, 9813)))
    _seed_stage_wide(test_db, run_id, members)
    first = _stage_wide_begin(test_db, run_id)

    def retire(conn, execution, *, digest):
        finish_plan_execution(conn, execution, state="aborted", reason="test retire")
        return True

    monkeypatch.setattr(
        qa_plan_execution_begin, "retire_unstarted_changed_roster", retire
    )
    probe, reads, _locked = _record_roster_reads(
        test_db, monkeypatch, run_id, [True, False]
    )
    try:
        second = _stage_wide_begin(test_db, run_id)
    finally:
        probe.close()
    # The first read, the read after retiring, and the read after a stale lock.
    assert reads == [False, False, False]
    assert second["id"] != first["id"]
