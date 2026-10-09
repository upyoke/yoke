"""Case-detail run history shares the native actual-attempt selection."""

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_reads import handle_qa_run_list


def _read(requirement_id):
    return handle_qa_run_list(
        FunctionCallRequest(
            function="qa.run.list",
            actor=ActorContext(actor_id="2", session_id="case-reader"),
            target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
            payload={"requirement_id": requirement_id},
        )
    )


@pytest.mark.parametrize(
    "second_start,current_index",
    [("2026-09-30T20:00:00-04:00", 0), ("2026-09-30T20:00:01-04:00", 1)],
)
def test_run_history_selects_utc_start_then_equal_instant_id(
    test_db, second_start, current_index
):
    item = insert_item(test_db, title="Read the current attempt")
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    first = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict="pass",
        started_at="2026-10-01T09:00:01+09:00",
        created_at="2026-10-02T00:00:00Z",
    )
    second = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict=None,
        started_at=second_start,
        created_at="2026-10-03T00:00:00Z",
    )
    before = [dict(first), dict(second)]
    outcome = _read(requirement["id"])
    assert outcome.primary_success, outcome.error
    rows = outcome.result_payload["rows"]
    assert rows[0]["id"] == before[current_index]["id"]
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    after = [
        dict(row)
        for row in test_db.execute(
            "SELECT * FROM qa_runs WHERE qa_requirement_id=%s ORDER BY id",
            (requirement["id"],),
        ).fetchall()
    ]
    assert after == before


def test_run_history_keeps_detached_review_without_selecting_it(test_db):
    item = insert_item(test_db, title="Read capture history")
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    capture = insert_qa_run(test_db, qa_requirement_id=requirement["id"], verdict=None)
    review = insert_qa_run(
        test_db, qa_requirement_id=requirement["id"], performed_by="agent"
    )
    test_db.execute(
        "INSERT INTO qa_plan_executions(id,item_id,transition_id,session_id,roster_digest,"
        "roster_json,state,created_at,heartbeat_at) VALUES('history-walk',%s,'done',"
        "'review-owner','digest','[]','completed',%s,%s)",
        (item["id"], review["created_at"], review["created_at"]),
    )
    test_db.execute(
        "INSERT INTO qa_plan_review_bundles(id,execution_id,roster_digest,state,bundle_digest,"
        "bundle_json,created_at) VALUES('history-review','history-walk','digest',"
        "'completed','digest','{}',%s)",
        (review["created_at"],),
    )
    test_db.execute(
        "INSERT INTO qa_plan_review_verdicts(bundle_id,requirement_id,capture_run_id,"
        "review_run_id,verdict,rationale,created_at) VALUES('history-review',%s,%s,%s,"
        "'pass','Historical judgment',%s)",
        (requirement["id"], capture["id"], review["id"], review["created_at"]),
    )
    test_db.commit()
    rows = _read(requirement["id"]).result_payload["rows"]
    assert [row["id"] for row in rows] == [capture["id"], review["id"]]
    assert rows[0]["verdict"] is None


def test_case_read_refuses_missing_start_instead_of_selecting_an_old_pass(test_db):
    item = insert_item(test_db, title="Ambiguous attempt start")
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    insert_qa_run(test_db, qa_requirement_id=requirement["id"])
    insert_qa_run(
        test_db, qa_requirement_id=requirement["id"], verdict=None, started_at=None
    )
    outcome = _read(requirement["id"])
    assert not outcome.primary_success
    assert outcome.error.code == "qa_execution_order_ambiguous"
