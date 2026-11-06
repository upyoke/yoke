"""Real PostgreSQL contention stays bounded and preserves the caller's work."""

from time import monotonic

import pytest

from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain.deployment_qa_shared_plan_reads import (
    read_plan_rows,
    plan_snapshot_row,
)
from yoke_core.domain.qa_plan_execution_store import select_plan_execution
from yoke_core.domain.qa_plan_lock import QaPlanBusy, bounded_plan_lock


@pytest.mark.parametrize("table", ["qa_plans", "qa_plan_executions"])
@pytest.mark.parametrize("mode", ["row", "table"])
def test_qa_lock_refuses_within_bound_and_preserves_transaction(test_db, table, mode):
    # Minimal temporary tables isolate the lock contract from plan lifecycle.
    test_db.execute(f"CREATE TABLE lock_fixture_{table} (id int PRIMARY KEY)")
    test_db.execute(f"INSERT INTO lock_fixture_{table} VALUES (1)")
    test_db.commit()
    # Use actual QA tables for table contention; row contention uses a seeded
    # execution/plan from the shared authority fixture below.
    from runtime.api.domain.qa_execution_request_subject_test_support import (
        _shared_execution,
    )

    execution = _shared_execution(test_db, "run-qa-lock", (9301, 9302))
    key = (
        execution["id"]
        if table == "qa_plan_executions"
        else test_db.execute("SELECT id FROM qa_plans ORDER BY id LIMIT 1").fetchone()[
            0
        ]
    )
    test_db.commit()
    holder = connect_test_database(test_db.info.dbname)
    try:
        if mode == "row":
            holder.execute(f"SELECT id FROM {table} WHERE id=%s FOR UPDATE", (key,))
        else:
            holder.execute(f"LOCK TABLE {table} IN SHARE MODE")
        test_db.execute("SET LOCAL lock_timeout = '7s'")
        test_db.execute(f"UPDATE lock_fixture_{table} SET id=2")
        started = monotonic()
        with pytest.raises(QaPlanBusy, match="qa_plan_busy:.*2000ms.*Retry"):
            with bounded_plan_lock(test_db, table):
                test_db.execute(
                    f"SELECT id FROM {table} WHERE id=%s FOR UPDATE", (key,)
                )
        assert 1.5 < monotonic() - started < 5
        assert test_db.execute("SHOW lock_timeout").fetchone()[0] == "7s"
        assert (
            test_db.execute(f"SELECT id FROM lock_fixture_{table}").fetchone()[0] == 2
        )
    finally:
        holder.rollback()
        holder.close()
    with bounded_plan_lock(test_db, table):
        test_db.execute(f"SELECT id FROM {table} WHERE id=%s FOR UPDATE", (key,))
    assert test_db.execute("SHOW lock_timeout").fetchone()[0] == "7s"


@pytest.mark.parametrize("reader", ["batch", "snapshot", "execution"])
def test_qa_readers_use_bounded_lock(test_db, reader):
    from runtime.api.domain.qa_execution_request_subject_test_support import (
        _shared_execution,
    )

    execution = _shared_execution(test_db, "run-qa-reader-lock", (9301, 9302))
    plan_id = test_db.execute("SELECT id FROM qa_plans ORDER BY id LIMIT 1").fetchone()[
        0
    ]
    test_db.commit()
    table = "qa_plan_executions" if reader == "execution" else "qa_plans"
    holder = connect_test_database(test_db.info.dbname)
    try:
        holder.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
        with pytest.raises(QaPlanBusy):
            if reader == "batch":
                read_plan_rows(test_db, [plan_id], lock_plan=True)
            elif reader == "snapshot":
                plan_snapshot_row(test_db, plan_id, lock_plan=True)
            else:
                select_plan_execution(test_db, execution["id"], lock=True)
        assert test_db.execute("SELECT 1").fetchone()[0] == 1
    finally:
        holder.rollback()
        holder.close()
