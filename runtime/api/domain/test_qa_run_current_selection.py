"""Case-detail run history shares the native actual-attempt selection."""

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_reads import handle_qa_run_list
from yoke_core.domain import db_helpers
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review


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


def test_current_selection_uses_the_returned_history_snapshot(test_db, monkeypatch):
    item = insert_item(test_db, title="Consistent current history")
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    current = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict="pass",
        started_at="2026-10-01T00:00:01Z",
    )
    old = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict=None,
        started_at="2026-10-01T00:00:00Z",
    )
    query = db_helpers.query_rows
    inserted = []

    def read_then_insert(conn, sql, params=()):
        rows = query(conn, sql, params)
        if "AS actual_execution" in sql and not inserted:
            inserted.append(
                insert_qa_run(
                    test_db,
                    qa_requirement_id=requirement["id"],
                    verdict=None,
                    started_at="2026-10-01T00:00:02Z",
                )["id"]
            )
        return rows

    monkeypatch.setattr(db_helpers, "query_rows", read_then_insert)
    outcome = _read(requirement["id"])
    assert outcome.primary_success, outcome.error
    rows = outcome.result_payload["rows"]
    assert inserted
    assert [row["id"] for row in rows] == [current["id"], old["id"]]
    assert inserted[0] not in [row["id"] for row in rows]


@pytest.mark.parametrize(
    "second_start,current_is_capture",
    [("2026-09-30T20:00:00-04:00", True), ("2026-09-30T20:00:01-04:00", False)],
)
def test_reviewed_capture_history_keeps_utc_selection_and_original_evidence(
    test_db, second_start, current_is_capture
):
    execution, requirement_id, capture_id = captured_plan_review(test_db, 4873)
    test_db.execute(
        "UPDATE qa_runs SET started_at=%s WHERE id=%s",
        ("2026-10-01T09:00:01+09:00", capture_id),
    )
    test_db.commit()
    before = dict(
        test_db.execute("SELECT * FROM qa_runs WHERE id=%s", (capture_id,)).fetchone()
    )
    pending = insert_qa_run(
        test_db,
        qa_requirement_id=requirement_id,
        verdict=None,
        case_outcome="needs_review",
        started_at=second_start,
    )
    bundle = begin_plan_review(test_db, execution)
    submit_plan_review(
        test_db,
        execution,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[
            {
                "requirement_id": requirement_id,
                "verdict": "pass",
                "rationale": "The captured frame matches the contract.",
            }
        ],
        reviewer_actor_id=None,
        reviewer_session_id="review-session",
    )
    test_db.commit()
    outcome = _read(requirement_id)
    assert outcome.primary_success, outcome.error
    rows = outcome.result_payload["rows"]
    assert rows[0]["id"] == (capture_id if current_is_capture else pending["id"])
    assert rows[0]["case_outcome"] == (
        "passed" if current_is_capture else "needs_review"
    )
    capture = next(row for row in rows if row["id"] == capture_id)
    assert capture["case_outcome"] == "passed"
    assert capture["verdict"] == "pass"
    assert capture["raw_result"] == before["raw_result"]
    stored = dict(
        test_db.execute("SELECT * FROM qa_runs WHERE id=%s", (capture_id,)).fetchone()
    )
    for key in (
        "case_outcome",
        "raw_result",
        "execution_status",
        "started_at",
        "completed_at",
    ):
        assert stored[key] == before[key]
    assert stored["case_outcome"] == "needs_review"
    assert len(rows) == 2
