"""Start-order selection against an independent shrinking symbolic ledger."""

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings, strategies as st
import pytest

from runtime.api.domain.qa_requirement_state_oracle import Attempt, current_attempt
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_latest_execution import (
    latest_execution_id_sql,
    latest_executions,
)


@settings(max_examples=20, deadline=None)
@given(
    st.lists(
        st.tuples(st.integers(0, 8), st.sampled_from([None, "pass", "fail", "error"])),
        min_size=1,
        max_size=6,
    )
)
def test_native_selector_matches_symbolic_start_order(ledger):
    with test_database() as conn:
        requirement_id = conn.execute(
            "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,"
            "requirement_source,workflow_transition_id,created_at) "
            "VALUES(1,'unit_test','verification','blocking','explicit','done',%s) "
            "RETURNING id",
            ("2026-10-01T00:00:00Z",),
        ).fetchone()[0]
        attempts = []
        epoch = datetime(2026, 10, 1, tzinfo=timezone.utc)
        for start, verdict in ledger:
            instant = epoch + timedelta(microseconds=start)
            # Equal/unequal starts and verdicts deliberately arrive shuffled.
            run_id = conn.execute(
                "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,"
                "verdict,started_at,completed_at,created_at) "
                "VALUES(%s,'agent','unit_test',%s,%s,%s,%s) RETURNING id",
                (
                    requirement_id,
                    verdict,
                    instant.isoformat(),
                    instant.isoformat() if verdict else None,
                    epoch.isoformat(),
                ),
            ).fetchone()[0]
            attempts.append(Attempt(run_id, requirement_id, instant, verdict))
        expected = current_attempt(attempts, requirement_id)
        selected = latest_executions(conn, [requirement_id])[requirement_id]
        assert selected["id"] == expected.id
        assert selected["verdict"] == expected.verdict
        sql_id = conn.execute(
            latest_execution_id_sql("%s"), (requirement_id,)
        ).fetchone()[0]
        assert sql_id == expected.id


@pytest.mark.parametrize("start", [None, "2026-10-01T00:00:00", "invalid"])
def test_invalid_start_is_named_instead_of_rescuing_old_pass(start):
    from yoke_core.domain.qa_latest_execution import execution_start

    with pytest.raises(ValueError, match="qa_execution_order_ambiguous"):
        execution_start(dict(id=17, started_at=start))
