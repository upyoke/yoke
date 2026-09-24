"""Run-bound member cases retain their discharge at the item's done gate."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.fixtures.deployment_admitted_case_fixture import (
    deliver_with_failing_admitted_copy,
    member_stage_acceptance,
    succeed_run,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_source_obligation import unsatisfied_blocking
from yoke_core.domain.qa_requirement_supersession import supersede_requirement


def _run_bound_failure(conn, *, item_id: int, run_id: str) -> tuple[int, int]:
    _insert_dash(conn, item_id=item_id, status="release")
    intake_id, broken_id, corrected_id = deliver_with_failing_admitted_copy(
        conn, item_id=item_id, run_id=run_id, corrected=True
    )
    # The same failing case is independently authored on the run rather than
    # admitted from item intake. Its intake source is waived for this fixture.
    conn.execute(
        "UPDATE qa_requirements SET plan_case_key='explicit-run-case' WHERE id=%s",
        (broken_id,),
    )
    conn.execute(
        "UPDATE qa_requirements SET waived_at='2026-09-24T00:00:00Z' WHERE id=%s",
        (intake_id,),
    )
    conn.commit()
    return broken_id, corrected_id


def _blocked(conn, item_id: int) -> tuple[int, ...]:
    result = unsatisfied_blocking(conn, item_id=item_id, target_status="done")
    return tuple(int(row["id"]) for row in result.rows)


def test_accepted_same_scope_replacement_settles_run_bound_failure(test_db) -> None:
    item_id = 2450
    run_id = "run-bound-superseded"
    broken_id, corrected_id = _run_bound_failure(
        test_db, item_id=item_id, run_id=run_id
    )
    assert broken_id in _blocked(test_db, item_id)
    supersede_requirement(
        test_db,
        requirement_id=broken_id,
        superseded_by_requirement_id=corrected_id,
        rationale="corrected case proved the deployed target",
    )
    deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="member-qa", member_item_id=item_id
    )
    assert member_stage_acceptance(test_db, run_id, item_id).accepted
    succeed_run(test_db, run_id)
    assert broken_id not in _blocked(test_db, item_id)


def test_unsuperseded_run_bound_failure_still_blocks(test_db) -> None:
    item_id = 2451
    run_id = "run-bound-unsettled"
    broken_id, _ = _run_bound_failure(test_db, item_id=item_id, run_id=run_id)
    succeed_run(test_db, run_id)
    assert broken_id in _blocked(test_db, item_id)


@pytest.mark.parametrize(
    "invalid_replacement", ["failed", "wrong-stage", "wrong-target"]
)
def test_forced_invalid_replacement_cannot_settle_run_bound_failure(
    test_db, invalid_replacement: str
) -> None:
    item_id = 2452
    run_id = f"run-bound-{invalid_replacement}"
    broken_id, corrected_id = _run_bound_failure(
        test_db, item_id=item_id, run_id=run_id
    )
    if invalid_replacement == "failed":
        test_db.execute(
            "UPDATE qa_runs SET verdict='fail' WHERE qa_requirement_id=%s",
            (corrected_id,),
        )
    elif invalid_replacement == "wrong-stage":
        test_db.execute(
            "UPDATE qa_requirements SET deployment_stage='other-stage' WHERE id=%s",
            (corrected_id,),
        )
    else:
        test_db.execute(
            "UPDATE qa_requirements SET execution_target_digest='other-target' "
            "WHERE id=%s",
            (corrected_id,),
        )
    test_db.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s WHERE id=%s",
        (corrected_id, broken_id),
    )
    test_db.commit()
    succeed_run(test_db, run_id)
    assert broken_id in _blocked(test_db, item_id)
