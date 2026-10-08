"""Start-order selection against an independent shrinking symbolic ledger."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings, strategies as st
import pytest

from runtime.api.domain.qa_requirement_state_oracle import (
    Attempt,
    Obligation,
    authorized,
    current_attempt,
    effective,
)
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


@settings(max_examples=100, deadline=None)
@given(
    st.lists(
        st.sampled_from([None, "pass", "fail", "error", "undetermined"]),
        min_size=1,
        max_size=8,
    ),
    st.booleans(),
    st.booleans(),
)
def test_symbolic_ledger_conjunction_scope_and_frozen_definition(
    verdicts, wrong_scope, sealed
):
    instant = datetime(2026, 10, 1, tzinfo=timezone.utc)
    scope = ("owner", "member", "stage", "environment", "observed-build")
    rows = [Obligation(i + 1, scope) for i in range(len(verdicts))]
    attempts = [
        Attempt(i + 1, i + 1, instant, verdict, subject=scope)
        for i, verdict in enumerate(verdicts)
    ]
    expected = all(verdict == "pass" for verdict in verdicts)
    assert authorized(rows, attempts) == expected
    assert (
        authorized([replace(row, display="renamed") for row in rows], attempts)
        == expected
    )
    changed = [replace(row, behavior="changed") for row in rows]
    assert not authorized(changed, attempts)
    frozen = [replace(row, frozen_behavior="original") for row in changed]
    assert authorized(frozen, attempts) == expected
    foreign = [
        replace(attempt, subject=("another-environment",)) for attempt in attempts
    ]
    if wrong_scope:
        assert not authorized(rows, foreign)
    assert not authorized(rows, attempts, live_ownership=True)
    assert authorized(rows, foreign, terminal_sealed=sealed) == sealed
    assert not authorized(rows + [Obligation(len(rows) + 1, scope)], attempts)
    assert not authorized([], [], required_setup=False)
    assert authorized([], [], qa_required=False)
    assert authorized([replace(row, discharged=True) for row in rows], [])


@settings(max_examples=100, deadline=None)
@given(st.integers(1, 8), st.sampled_from([None, "pass", "fail", "error"]))
def test_symbolic_replacement_grades_only_final_successor(length, verdict):
    scope = ("item", "transition", "phase", "environment")
    rows = [
        Obligation(i, scope, successor=i + 1 if i < length else None)
        for i in range(1, length + 1)
    ]
    instant = datetime(2026, 10, 1, tzinfo=timezone.utc)
    history = [Attempt(i, i, instant, "pass", subject=scope) for i in range(1, length)]
    current = Attempt(length, length, instant, verdict, subject=scope)
    assert [row.id for row in effective(rows)] == [length]
    assert authorized(rows, history + [current]) == (verdict == "pass")
    assert not authorized(rows, history)
    with pytest.raises(ValueError, match="cycle"):
        effective(
            [replace(row, successor=1) if row.id == length else row for row in rows]
        )
    with pytest.raises(ValueError, match="invalid successor scope"):
        effective([Obligation(1, scope, successor=2), Obligation(2, ("foreign",))])


@settings(max_examples=100, deadline=None)
@given(st.integers(1, 20), st.integers(0, 8), st.integers(0, 8))
def test_symbolic_review_and_insert_order_cannot_rescue_newer_pending(
    base_id, first, second
):
    epoch = datetime(2026, 10, 1, tzinfo=timezone.utc)
    scope = ("observed",)
    older = Attempt(
        base_id, 1, epoch + timedelta(microseconds=first), "pass", subject=scope
    )
    newer = Attempt(
        base_id + 1, 1, epoch + timedelta(microseconds=second), None, subject=scope
    )
    judgment = Attempt(
        base_id + 2,
        1,
        epoch + timedelta(days=1),
        "pass",
        review_of=base_id,
        subject=scope,
    )
    selected = current_attempt([newer, judgment, older], 1)
    assert selected.id == (newer.id if second >= first else older.id)
    assert authorized([Obligation(1, scope)], [older, newer, judgment]) == (
        first > second
    )
    assert current_attempt([judgment, older, newer], 1) == selected


@settings(max_examples=15, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from([None, "pass", "fail", "error", "undetermined"]),
            st.booleans(),
            st.booleans(),
            st.booleans(),
            st.booleans(),
        ),
        min_size=1,
        max_size=4,
    )
)
def test_native_current_currency_and_effective_conjunction_match_oracle(cases):
    import json
    from runtime.api.fixtures.backlog_qa_inserts import (
        insert_qa_requirement,
        insert_qa_run,
    )
    from yoke_core.domain.qa_obligation_settlement import obligation_settled
    from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run

    with test_database() as conn:
        obligations, attempts, native = [], [], []
        instant = datetime(2026, 10, 1, tzinfo=timezone.utc)
        for verdict, complete, correct_behavior, correct_subject, discharged in cases:
            requirement = insert_qa_requirement(
                conn,
                item_id=1,
                method_config=json.dumps({"definition": "original"}),
                execution_target_digest="subject",
                waived_at=instant.isoformat() if discharged else None,
            )
            requirement_id = int(requirement["id"])
            obligations.append(
                Obligation(requirement_id, ("subject",), discharged=discharged)
            )
            native.append(requirement)
            older = insert_qa_run(
                conn,
                qa_requirement_id=requirement_id,
                verdict="pass",
                started_at=(instant - timedelta(seconds=1)).isoformat(),
                raw_result=json.dumps(
                    {
                        "method_config": {"definition": "original"},
                        "execution_target_digest": "subject",
                    }
                ),
            )
            attempts.append(
                Attempt(
                    older["id"],
                    requirement_id,
                    instant - timedelta(seconds=1),
                    "pass",
                    subject=("subject",),
                )
            )
            behavior = "original" if correct_behavior else "foreign"
            subject = "subject" if correct_subject else "another-target"
            current = insert_qa_run(
                conn,
                qa_requirement_id=requirement_id,
                verdict=verdict,
                verdict_reason="Evidence is inconclusive"
                if verdict == "undetermined"
                else None,
                started_at=instant.isoformat(),
                completed_at=instant.isoformat() if complete else None,
                raw_result=json.dumps(
                    {
                        "method_config": {"definition": behavior},
                        "execution_target_digest": subject,
                    }
                ),
            )
            attempts.append(
                Attempt(
                    current["id"],
                    requirement_id,
                    instant,
                    verdict,
                    completed=complete,
                    behavior=behavior,
                    subject=(subject,),
                )
            )
        actual = all(
            obligation_settled(row) or has_current_passing_run(conn, row["id"])
            for row in native
        )
        assert actual == authorized(obligations, attempts)
