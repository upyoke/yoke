"""Operator questions cross the real handler, Postgres and Fleet boundaries."""

from __future__ import annotations

import importlib

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _project,
    seed_session,
    _bodies,
    _recipients,
)
from runtime.api.domain.coordination_claim_test_support import PROJECT_YOKE
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.decision_request_questions import handle_ask, handle_list
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.inbox_read import inbox_for_actor


def _call(function, session, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="1", session_id=session),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_worker_files_without_steering_and_receives_one_engine_answer(
    test_db, monkeypatch
):
    _project(test_db)
    session = "question-worker"
    seed_session(test_db, session)
    # The handler borrows the fixture while retaining its own context-manager boundary.
    from contextlib import contextmanager

    @contextmanager
    def connection():
        yield test_db

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", connection)
    filed = handle_ask(
        _call(
            "decision_requests.ask",
            session,
            {
                "key": "choose-color",
                "question": "Which color?",
                "options": [{"id": "blue", "label": "Blue"}],
                "recommended_option": "blue",
            },
        )
    )
    assert filed.primary_success, filed.error
    request = filed.result_payload["request"]
    assert request["requesting_session_id"] == session
    listed = handle_list(_call("decision_requests.list", session, {}))
    assert listed.primary_success, listed.error
    assert [q["id"] for q in listed.result_payload["questions"]] == [request["id"]]
    waiting = inbox_for_actor(
        test_db, actor_id=1, project_ids=[PROJECT_YOKE], include_read=False
    )
    assert request["id"] in [row["id"] for row in waiting["needs_decision"]]
    answered = resolve_decision_request(
        test_db, request["id"], actor_id=1, action="blue", session_id="steering-chat"
    )
    assert answered["status"] == "resolved"
    assert "reason" not in answered["subject_context"]["answer_delivery"]
    key = f"operator-question-answer:{request['id']}"
    assert _recipients(test_db, key) == [session]
    [body] = _bodies(test_db, key)
    assert "Which color?" in body and "Blue" in body
    sender = test_db.execute(
        "SELECT sender_actor_id FROM session_messages WHERE idempotency_key=%s", (key,)
    ).fetchone()
    assert sender[0] is None  # Canonical engine identity renders as Yoke.
    decided = inbox_for_actor(
        test_db, actor_id=1, project_ids=[PROJECT_YOKE], include_read=False
    )
    row = next(row for row in decided["needs_decision"] if row["id"] == request["id"])
    assert row["decided_by_you"] and row["actions"] == []


def test_migration_admits_questions_preserves_gates_and_carries_floor(test_db):
    migration = importlib.import_module(
        "yoke_core.domain.migrations.0100_operator_questions"
    )
    test_db.execute(
        "ALTER TABLE decision_requests DROP CONSTRAINT decision_requests_kind_check"
    )
    test_db.execute(
        "ALTER TABLE decision_requests ADD CONSTRAINT decision_requests_kind_check CHECK(kind IN ('deployment_stage_approval', 'qa_needs_review', 'lifecycle_transition_approval', 'machine_approval', 'merge_candidate_review'))"
    )
    migration.apply(test_db)
    migration.invariants(test_db)
    migration.apply(test_db)
    assert migration.MINIMUM_SERVING_VERSION == "next-release"
    assert "operator_question" in migration.ALL_KINDS
    assert (
        test_db.execute(
            "SELECT requesting_session_id FROM decision_requests LIMIT 1"
        ).fetchone()
        is None
    )


def test_terminal_item_questions_are_disposed(test_db):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from runtime.api.domain.test_deployment_qa_stage_wake_delivery import _claim
    from yoke_core.domain.work_claim_targets import make_item_target
    from yoke_core.domain.decision_request_question_filing import file_question
    from yoke_core.domain.decision_requests import RoleAuthority
    from yoke_core.domain.decision_request_disposition import (
        dispose_ended_decision_requests,
    )
    from yoke_core.domain.decision_request_rows import request_row

    _project(test_db)
    session = "question-item-worker"
    seed_session(test_db, session)
    item_id = 9711
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    _claim(
        test_db,
        session_id=session,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    question, _ = file_question(
        test_db,
        kind="operator_question",
        subject_type="session_question",
        subject_key=f"{session}:choose",
        requesting_session_id=session,
        session_id=session,
        project_id=PROJECT_YOKE,
        originator_actor_id=1,
        role_authorities=[RoleAuthority("project", PROJECT_YOKE, "owner")],
        subject_context={"question": "What next?", "item_id": item_id},
    )
    test_db.execute("UPDATE items SET status='cancelled' WHERE id=%s", (item_id,))
    test_db.commit()
    receipt = dispose_ended_decision_requests(test_db, project_ids=[PROJECT_YOKE])
    assert question["id"] in [row["request_id"] for row in receipt["withdrawn"]]
    assert request_row(test_db, question["id"])["status"] == "withdrawn"
