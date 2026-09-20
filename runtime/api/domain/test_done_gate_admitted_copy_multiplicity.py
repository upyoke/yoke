"""Done settles when every admitted copy of an intake source is accepted.

The completion-run read used to require exactly one admitted row. Two
accepted copies of the same intake — the same member, the same succeeded
run — then looked identical to zero copies, and the item could not reach
done. Duplication is a materialization fact; the gate asks whether any copy
is still unsettled.
"""

from __future__ import annotations

from runtime.api.domain.test_dash_post_deploy_done_consumption import (
    _accept_member_qa,
    _bind_original,
)
from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _seed_selected_requirement_run,
)
from runtime.api.domain.test_post_deploy_original_pass_needs_admission import (
    _record_evidence,
)
from runtime.api.fixtures.backlog_inserts import insert_qa_run
from runtime.api.fixtures.deployment_admitted_case_fixture import succeed_run
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.deployment_qa_source_obligation import (
    source_obligation_consumed,
)
from yoke_core.domain.qa_gates import GateTarget, check_done_gate


def _admitted_copy_ids(conn, *, run_id: str, intake_id: int) -> list[int]:
    key = admitted_requirement_case_key(intake_id)
    rows = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND plan_case_key=%s AND plan_id IS NULL ORDER BY id",
        (run_id, key),
    ).fetchall()
    return [int(row["id"] if hasattr(row, "keys") else row[0]) for row in rows]


def _out_of_scope_admitted_copy(conn, *, source_copy_id: int) -> int:
    """Second admitted row of the same intake, off the live target digest."""
    columns = [
        str(row[0])
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='qa_requirements' AND column_name<>'id' "
            "ORDER BY ordinal_position"
        ).fetchall()
    ]
    projected = [
        "case_position+1"
        if column == "case_position"
        else "'drifted-' || COALESCE(execution_target_digest, 'none')"
        if column == "execution_target_digest"
        else "NULL"
        if column in ("superseded_by_requirement_id", "superseded_at")
        else column
        for column in columns
    ]
    row = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) "
        f"SELECT {','.join(projected)} FROM qa_requirements WHERE id=%s "
        "RETURNING id",
        (int(source_copy_id),),
    ).fetchone()
    conn.commit()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _deliver_intake(conn, *, item_id: int, run_id: str) -> int:
    _insert_dash(conn, item_id=item_id, status="release")
    intake_id = _bind_original(conn, item_id=item_id)
    insert_qa_run(conn, qa_requirement_id=intake_id, verdict="pass")
    _seed_selected_requirement_run(
        conn, run_id=run_id, item_id=item_id, requirement_id=intake_id
    )
    return intake_id


def _assert_gate(conn, *, item_id: int, intake_id: int, settles: bool) -> None:
    consumed = source_obligation_consumed(
        conn, item_id=item_id, source_requirement_id=intake_id
    )
    db_path = str(conn.info.dsn)
    shared = check_done_gate(GateTarget(item_id=item_id), db_path)
    blocked = evaluate(item_id=item_id, target_status="done", db_path=db_path)
    if settles:
        assert consumed
        assert shared.passed is True
        assert blocked is None
        return
    assert not consumed
    assert shared.passed is False
    assert any(f"#{intake_id}" in error for error in shared.errors)
    assert blocked is not None


def test_two_accepted_admitted_copies_settle_done(test_db) -> None:
    item_id = 2410
    run_id = "run-two-accepted-copies"
    intake_id = _deliver_intake(test_db, item_id=item_id, run_id=run_id)
    _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
    copies = _admitted_copy_ids(test_db, run_id=run_id, intake_id=intake_id)
    assert len(copies) == 1
    second = _out_of_scope_admitted_copy(test_db, source_copy_id=copies[0])
    insert_qa_run(test_db, qa_requirement_id=second, verdict="pass")
    assert (
        _admitted_copy_ids(test_db, run_id=run_id, intake_id=intake_id)
        == copies + [second]
    )
    _record_evidence(test_db, item_id=item_id)
    _assert_gate(test_db, item_id=item_id, intake_id=intake_id, settles=True)


def test_zero_admitted_copies_on_a_succeeded_run_still_hold_done(test_db) -> None:
    item_id = 2411
    run_id = "run-zero-admitted-copies"
    intake_id = _deliver_intake(test_db, item_id=item_id, run_id=run_id)
    succeed_run(test_db, run_id)
    assert _admitted_copy_ids(test_db, run_id=run_id, intake_id=intake_id) == []
    _record_evidence(test_db, item_id=item_id)
    _assert_gate(test_db, item_id=item_id, intake_id=intake_id, settles=False)


def test_an_unsettled_duplicate_copy_still_holds_done(test_db) -> None:
    item_id = 2412
    run_id = "run-unsettled-duplicate-copy"
    intake_id = _deliver_intake(test_db, item_id=item_id, run_id=run_id)
    _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
    copies = _admitted_copy_ids(test_db, run_id=run_id, intake_id=intake_id)
    second = _out_of_scope_admitted_copy(test_db, source_copy_id=copies[0])
    insert_qa_run(test_db, qa_requirement_id=second, verdict="fail")
    _record_evidence(test_db, item_id=item_id)
    _assert_gate(test_db, item_id=item_id, intake_id=intake_id, settles=False)
