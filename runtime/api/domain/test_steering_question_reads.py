"""Settled question history adds no description work to a fleet report."""

import json

import pytest

from runtime.api.domain.decision_request_operator_question_test_support import (
    conn as conn,
    filing,
)
from yoke_core.domain.decision_request_question_filing import file_question
from yoke_core.domain.decision_request_rows import request_rows
from yoke_core.domain import steering_fleet_report_questions as questions


def _ask(conn, index):
    conn.execute(
        "INSERT OR IGNORE INTO items (id,project_id,project_sequence,title,status,"
        "workflow_id,workflow_version_id) VALUES (?,10,?,'Work','implementing','issue',7)",
        (index, 100 + index),
    )
    return file_question(
        conn,
        **filing(
            subject_key=f"worker:question-{index}",
            subject_context={"question": f"Choose {index}?", "item_id": index},
        ),
    )[0]["id"]


@pytest.mark.parametrize("history", [1, 10, 30])
def test_resolved_history_is_filtered_before_description(conn, monkeypatch, history):
    ids = [_ask(conn, index) for index in range(1, history + 3)]
    conn.execute(
        "UPDATE decision_requests SET status='resolved', resolution_action='freeform', "
        "resolution_note='Blue' WHERE id<>?", (ids[-1],)
    )
    context = json.loads(conn.execute(
        "SELECT subject_context FROM decision_requests WHERE id=?", (ids[0],)
    ).fetchone()[0])
    context["answer_delivery"] = {"reason": "delivery failed"}
    conn.execute("UPDATE decision_requests SET subject_context=? WHERE id=?",
                 (json.dumps(context), ids[0]))
    previous = (ids[1],)
    visible = questions._visible
    # The previous algorithm describes every visible resolved question, then
    # applies the same display predicate; use it as the payload oracle.
    with monkeypatch.context() as old:
        old.setattr(questions, "_visible", lambda *a, **kw: visible(*a))
        expected = questions.read_questions(conn, "steering", previous)
    from yoke_core.domain import decision_request_rows
    described = []
    original = decision_request_rows.request_rows

    def capture(connection, request_ids):
        described.extend(request_ids)
        return original(connection, request_ids)

    monkeypatch.setattr(decision_request_rows, "request_rows", capture)
    assert questions.read_questions(conn, "steering", previous) == expected
    assert set(described) == {ids[0], ids[1], ids[-1]}
    # Polls still retain all unconsumed resolved identities for departure tracking.
    assert set(questions.question_states(conn, "steering", include_resolved=True)) == set(ids)
    conn.execute("UPDATE decision_requests SET status='pending' WHERE id=?", (ids[2],))
    assert ids[2] in {q.request_id for q in questions.read_questions(conn, "steering")}


@pytest.mark.parametrize("size", [1, 10, 30])
def test_question_page_batches_public_refs_and_refreshes(conn, size):
    conn.executemany(
        "INSERT INTO items (id,project_id,project_sequence,title,status,workflow_id,"
        "workflow_version_id) VALUES (?,10,?,'Work','implementing','issue',7)",
        [(index, 100 + index) for index in range(1, size + 1)],
    )
    ids = [_ask(conn, index) for index in range(1, size + 1)]
    statements = []
    conn.set_trace_callback(statements.append)
    rows = request_rows(conn, ids)
    conn.set_trace_callback(None)
    refs = [sql for sql in statements if 'JOIN projects p ON p.id = i.project_id' in sql]
    assert len(refs) == 1
    assert [rows[key]["subject_context"]["item_ref"] for key in ids] == [
        f"YOK-{101 + index}" for index in range(size)
    ]
    conn.execute("UPDATE items SET project_sequence=999 WHERE id=1")
    assert request_rows(conn, ids)[ids[0]]["subject_context"]["item_ref"] == "YOK-999"
