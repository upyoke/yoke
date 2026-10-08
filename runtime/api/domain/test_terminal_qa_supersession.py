"""Superseded closed captures stop holding terminal item transitions."""

import json

import pytest

from runtime.api.domain.test_terminal_qa_settlement import (
    _seed_plan_execution,
    _terminal_result,
)
from runtime.api.domain.test_terminal_post_deploy_settlement import (
    _accept_member_qa,
    _source_member,
)
from runtime.api.fixtures.backlog import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.qa_terminal_settlement import find_unsettled_records
from yoke_core.domain.qa_terminal_settlement import terminal_transition_result
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime
from yoke_core.domain.deployment_run_collective_finalization import mark_settling


COMPLETED_AT = "2026-01-01T00:00:01Z"


def _seed_successor(test_db, *, verdict="pass", completed_at=COMPLETED_AT):
    successor = int(insert_qa_requirement(test_db, item_id=10)["id"])
    if verdict != "missing":
        insert_qa_run(
            test_db,
            qa_requirement_id=successor,
            verdict=verdict,
            verdict_reason="Conflicting evidence"
            if verdict == "undetermined"
            else None,
            completed_at=completed_at,
            performed_by="ci_run",
            raw_result=json.dumps({"verification_tree": {"head_sha": "a" * 40}}),
        )
    return successor


def _seed_old_run(
    test_db,
    successor,
    *,
    status="capture_failed",
    completed_at=COMPLETED_AT,
    case_outcome=None,
):
    requirement = int(
        insert_qa_requirement(
            test_db, item_id=10, superseded_by_requirement_id=successor
        )["id"]
    )
    run = insert_qa_run(
        test_db,
        qa_requirement_id=requirement,
        verdict=None,
        execution_status=status,
        case_outcome=case_outcome,
        completed_at=completed_at,
    )
    return requirement, int(run["id"])


def test_closed_superseded_capture_allows_done_without_rewriting_history(test_db):
    insert_item(test_db, id=10, status="release")
    successor = _seed_successor(test_db)
    _, old_run = _seed_old_run(test_db, successor)

    assert _terminal_result(test_db) == {"success": True}
    assert find_unsettled_records(test_db, item_id=10) == []
    row = test_db.execute(
        "SELECT verdict FROM qa_runs WHERE id=%s", (old_run,)
    ).fetchone()
    assert row[0] is None


@pytest.mark.parametrize("verdict", ["missing", None, "fail", "undetermined"])
def test_unsettled_successor_is_named_at_done(test_db, verdict):
    insert_item(test_db, id=10, status="release")
    successor = _seed_successor(test_db, verdict=verdict)
    _seed_old_run(test_db, successor)

    result = _terminal_result(test_db)

    assert result["error_code"] == (
        "GATE_QA_TERMINAL_SETTLEMENT" if verdict is None else "GATE_QA_TERMINAL_VERDICT"
    )
    assert str(successor) in result["error"]
    assert (
        "pending verdict" in result["error"]
        if verdict is None
        else f"Requirement #{successor}" in result["error"]
    )


def test_successor_pass_without_completion_still_blocks(test_db):
    insert_item(test_db, id=10, status="release")
    successor = _seed_successor(test_db, completed_at=None)
    _seed_old_run(test_db, successor)

    assert (
        f"Requirement #{successor} [incomplete]" in _terminal_result(test_db)["error"]
    )


@pytest.mark.parametrize(
    ("status", "completed_at", "case_outcome"),
    [
        (None, None, "running"),
        (None, COMPLETED_AT, "running"),
        (None, COMPLETED_AT, "waiting"),
        ("captured", None, None),
        ("capture_failed", None, None),
    ],
)
def test_unfinished_superseded_attempt_remains_history(
    test_db, status, completed_at, case_outcome
):
    insert_item(test_db, id=10, status="release")
    successor = _seed_successor(test_db)
    _, old_run = _seed_old_run(
        test_db,
        successor,
        status=status,
        completed_at=completed_at,
        case_outcome=case_outcome,
    )

    result = _terminal_result(test_db)

    assert result == {"success": True}
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (old_run,)
        ).fetchone()[0]
        is None
    )


def test_live_plan_execution_still_blocks_with_settled_successor(test_db):
    insert_item(test_db, id=10, status="release")
    successor = _seed_successor(test_db)
    _seed_old_run(test_db, successor)
    _seed_plan_execution(test_db, state="active")

    assert "active execution remains active" in _terminal_result(test_db)["error"]


@pytest.mark.parametrize("discharge", ["waived_at", "retracted_at"])
def test_discharged_successor_settles_closed_old_attempt(test_db, discharge):
    insert_item(test_db, id=10, status="release")
    _seed_successor(test_db)
    successor = int(
        insert_qa_requirement(test_db, item_id=10, **{discharge: COMPLETED_AT})["id"]
    )
    _seed_old_run(test_db, successor)

    assert _terminal_result(test_db) == {"success": True}


def test_supersession_chain_uses_the_final_successor(test_db):
    insert_item(test_db, id=10, status="release")
    successor = _seed_successor(test_db)
    middle, _ = _seed_old_run(test_db, successor)
    _seed_old_run(test_db, middle)

    assert _terminal_result(test_db) == {"success": True}


def test_closed_unsuperseded_attempt_still_blocks(test_db):
    insert_item(test_db, id=10, status="release")
    _seed_successor(test_db)
    _seed_old_run(test_db, None)

    assert _terminal_result(test_db)["error_code"] == "GATE_QA_TERMINAL_SETTLEMENT"


def test_successor_with_a_new_live_attempt_still_blocks(test_db):
    insert_item(test_db, id=10, status="release")
    successor = _seed_successor(test_db)
    _seed_old_run(test_db, successor)
    insert_qa_run(test_db, qa_requirement_id=successor, verdict=None)

    assert (
        f"requirement {successor} latest execution"
        in _terminal_result(test_db)["error"]
    )


@pytest.mark.parametrize("accepted", [True, False])
def test_post_deploy_successor_requires_accepted_completion_member(test_db, accepted):
    item_id, run_id, successor = _source_member(
        test_db, workflow="dash", plan_source=False
    )
    old_requirement = int(
        insert_qa_requirement(
            test_db,
            item_id=item_id,
            qa_phase="post_deploy",
            superseded_by_requirement_id=successor,
        )["id"]
    )
    insert_qa_run(
        test_db,
        qa_requirement_id=old_requirement,
        verdict=None,
        execution_status="capture_failed",
        completed_at=COMPLETED_AT,
    )
    if accepted:
        _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
    else:
        # Intake success cannot replace proof from the delivery's admitted copy.
        insert_qa_run(
            test_db,
            qa_requirement_id=successor,
            verdict="pass",
            completed_at=COMPLETED_AT,
        )
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    mark_settling(test_db, run_id)

    result = terminal_transition_result(
        test_db, item_id, "done", load_item_workflow_runtime(test_db, item_id)
    )

    if accepted:
        assert result is None
    else:
        assert result["error_code"] == "GATE_QA_TERMINAL_VERDICT"
        assert f"Requirement #{successor} [post-deploy-unaccepted]" in result["error"]
