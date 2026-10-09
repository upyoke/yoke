"""Plan unions grade effective corrections and retain source cases as history."""

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from runtime.api.fixtures.qa_declared_replacement_fixture import corrected_case, declare
from yoke_core.domain.qa_plan_case_proof import _case_result
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases


def _cases(conn, plan_id, keys):
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "command",
                "instructions": "Run the corrected command.",
                "expected_outcome": "It passes.",
                "method_config": {"command": "true"},
            }
            for position, key in enumerate(keys, 1)
        ],
    )


def _replacement(conn):
    item = insert_item(conn, title="Effective case union")
    plan = create_plan(
        conn, project="yoke", slug="effective-case-union", name="Effective cases"
    )
    plan_id = int(plan["id"])
    _cases(conn, plan_id, ["original", "corrected"])
    old_id = int(
        insert_qa_requirement(
            conn,
            item_id=item["id"],
            plan_id=plan_id,
            plan_case_key="original",
            method_id="command",
            qa_kind="plan_case",
            method_config='{"command":"true"}',
        )["id"]
    )
    record_case_verdict(conn, old_id, "fail", evidence=False)
    successor = corrected_case(conn, failed_id=old_id, case_key="corrected")
    declare(conn, old_id, "corrected", [successor])
    return plan_id, old_id, successor


@pytest.mark.parametrize(
    "verdict,outcome", [(None, "queued"), ("fail", "failed"), ("pass", "passed")]
)
def test_replacement_grades_only_successor_without_retired_not_run(
    test_db, verdict, outcome
):
    plan_id, old_id, successor = _replacement(test_db)
    if verdict:
        record_case_verdict(test_db, successor, verdict, evidence=False)
    detail = get_plan(test_db, plan_id=plan_id)
    assert [case["case_key"] for case in detail["cases"]] == ["original", "corrected"]
    assert detail["cases"][0]["proofs"] == []
    assert detail["cases"][1]["last_result"]["requirement_id"] == successor
    assert detail["union"] == {"satisfied": verdict == "pass", "counts": {outcome: 1}}
    assert _case_result(test_db, plan_id, "original", None, None) is None
    # A retirement in another baseline or environment cannot erase missing proof.
    assert (
        _case_result(test_db, plan_id, "original", "fresh-host", None)["outcome"]
        == "not_run"
    )
    assert (
        _case_result(test_db, plan_id, "original", None, None, "stage")["outcome"]
        == "not_run"
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s", (old_id,)
        ).fetchone()[0]
        == 1
    )


def test_never_materialized_case_still_holds_union_after_replacement_pass(test_db):
    plan_id, _old_id, successor = _replacement(test_db)
    record_case_verdict(test_db, successor, "pass", evidence=False)
    _cases(test_db, plan_id, ["original", "corrected", "unmaterialized"])
    detail = get_plan(test_db, plan_id=plan_id)
    assert detail["cases"][2]["last_result"]["requirement_id"] is None
    assert detail["union"] == {
        "satisfied": False,
        "counts": {"passed": 1, "not_run": 1},
    }


def test_invalid_retirement_graph_refuses_plan_union(test_db):
    plan_id, old_id, successor = _replacement(test_db)
    test_db.execute(
        "UPDATE qa_requirements SET replacement_requirement_id=%s WHERE id=%s",
        (old_id, successor),
    )
    test_db.commit()
    with pytest.raises(ValueError, match="replacement_graph_invalid: correction cycle"):
        get_plan(test_db, plan_id=plan_id)
