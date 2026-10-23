"""Ownership lock contention rolls back only the attempted takeover."""

from time import monotonic

import pytest

from runtime.api.domain.test_deployment_qa_takeover_identity import _execution
from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.fixtures.pg_testdb import connect_test_database


def test_busy_execution_preserves_caller_writes_and_allows_exact_retry(
    test_db, monkeypatch
):
    from yoke_core.domain import deployment_runs_lock

    execution = _execution(test_db, monkeypatch)
    third = "run-lock-retry"
    test_db.execute(
        "UPDATE deployment_runs SET status='failed' WHERE id=%s", (takeover.NEW,)
    )
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,created_at) SELECT %s,project_id,flow,target_tier,"
        "target_environment_id,%s,'created',created_at FROM deployment_runs WHERE id=%s",
        (third, "d" * 40, takeover.NEW),
    )
    test_db.commit()
    holder = connect_test_database(test_db.info.dbname)
    previous = test_db.execute("SHOW lock_timeout").fetchone()[0]
    monkeypatch.setattr(deployment_runs_lock, "RUN_ROW_LOCK_TIMEOUT_MS", 50)
    try:
        holder.execute(
            "SELECT id FROM qa_plan_executions WHERE id=%s FOR UPDATE",
            (execution["id"],),
        )
        test_db.execute(
            "UPDATE deployment_runs SET artifact_identity='caller-marker' WHERE id=%s",
            (third,),
        )
        started = monotonic()
        with pytest.raises(ValueError, match="qa_ownership_busy"):
            takeover.take_over_waiting_run(
                test_db, third, session_id=takeover.DRIVER_SESSION
            )
        assert monotonic() - started < 5
        assert test_db.execute("SHOW lock_timeout").fetchone()[0] == previous
        assert (
            test_db.execute(
                "SELECT artifact_identity FROM deployment_runs WHERE id=%s",
                (third,),
            ).fetchone()[0]
            == "caller-marker"
        )
        assert (
            test_db.execute(
                "SELECT deployment_run_id FROM qa_plan_executions WHERE id=%s",
                (execution["id"],),
            ).fetchone()[0]
            == takeover.NEW
        )
        assert takeover._members(test_db, third) == set()
        assert takeover._members(test_db, takeover.NEW) == {takeover.WAITING}
    finally:
        holder.rollback()
        holder.close()
    assert (
        takeover.take_over_waiting_run(
            test_db,
            third,
            session_id=takeover.DRIVER_SESSION,
        )
        == takeover.NEW
    )
    assert (
        test_db.execute(
            "SELECT deployment_run_id FROM qa_plan_executions WHERE id=%s",
            (execution["id"],),
        ).fetchone()[0]
        == third
    )


def test_changed_preparation_refuses_before_transferring_any_record(
    test_db, monkeypatch
):
    from yoke_core.domain import deployment_run_takeover_read

    takeover._seed_old(test_db, run_qa=False)
    takeover._seed_new(test_db)
    takeover._contains(monkeypatch)
    original = deployment_run_takeover_read.read_takeover

    def changed(conn, new_run, old):
        prepared = original(conn, new_run, old)
        conn.execute(
            "UPDATE deployment_runs SET current_stage='deploy' WHERE id=%s",
            (takeover.OLD,),
        )
        return prepared

    monkeypatch.setattr(deployment_run_takeover_read, "read_takeover", changed)
    with pytest.raises(takeover.TakeoverRefused, match="takeover_inputs_changed"):
        takeover.take_over_waiting_run(
            test_db, takeover.NEW, session_id=takeover.DRIVER_SESSION
        )
    assert takeover._members(test_db, takeover.NEW) == set()
    assert takeover._members(test_db, takeover.OLD) == {
        takeover.PASSED,
        takeover.WAITING,
    }
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s",
            (takeover.NEW,),
        ).fetchone()[0]
        == 0
    )
