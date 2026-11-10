"""Operator questions cross the real handler, Postgres and Fleet boundaries."""

from __future__ import annotations

from runtime.api.domain.operator_question_integration_test_support import _call as _call


from runtime.api.fixtures.actor_roles import seed_org_role


from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    _project,
    seed_session,
    _bodies,
    _recipients,
)
from runtime.api.domain.coordination_claim_test_support import PROJECT_YOKE
from yoke_core.domain.handlers.decision_request_questions import handle_ask, handle_list
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.inbox_read import inbox_for_actor


def test_worker_files_without_steering_and_receives_one_engine_answer(
    test_db, monkeypatch
):
    _project(test_db)
    session = "question-worker"
    seed_session(test_db, session, launch_origin="yoke")
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


def test_terminal_item_questions_are_disposed(test_db):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import _claim
    from yoke_core.domain.work_claim_targets import make_item_target
    from yoke_core.domain.decision_request_question_filing import file_question
    from yoke_core.domain.decision_requests import RoleAuthority
    from yoke_core.domain.decision_request_disposition import (
        dispose_ended_decision_requests,
    )
    from yoke_core.domain.decision_request_rows import request_row

    _project(test_db)
    session = "question-item-worker"
    seed_session(test_db, session, launch_origin="yoke")
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


def test_question_outcomes_are_delivered_once(test_db):
    from dataclasses import replace
    from datetime import timedelta
    from yoke_core.domain.decision_request_question_filing import file_question
    from yoke_core.domain.decision_request_resolution import withdraw_decision_request
    from yoke_core.domain.decision_requests import RoleAuthority
    from yoke_core.domain.steering_fleet_report_questions import read_questions
    from yoke_core.domain.steering_fleet_report_compose import CombinedFleetReport
    from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest
    from runtime.api.domain.fleet_delta_reports_test_support import NOW

    _project(test_db)
    session = "question-worker"
    seed_session(test_db, session, launch_origin="yoke")
    ids = []
    for key in ("answer", "withdraw", "consume"):
        question, _ = file_question(
            test_db,
            kind="operator_question",
            subject_type="session_question",
            subject_key=f"{session}:{key}",
            requesting_session_id=session,
            session_id=session,
            project_id=PROJECT_YOKE,
            originator_actor_id=1,
            role_authorities=[RoleAuthority("project", PROJECT_YOKE, "owner")],
            subject_context={
                "question": "Which color?",
                "options": [{"id": "blue", "label": "Blue"}],
            },
        )
        ids.append(question["id"])
    before = CombinedFleetReport(NOW, (), questions=read_questions(test_db, session))
    prior = before.fingerprint()
    resolve_decision_request(
        test_db, ids[0], actor_id=1, action="blue", session_id=session
    )
    withdraw_decision_request(
        test_db, ids[1], reason="No longer needed", actor_id=1, session_id=session
    )
    test_db.execute(
        "UPDATE decision_requests SET consumed_at=%s WHERE id=%s", (NOW, ids[2])
    )
    test_db.commit()
    rows = read_questions(test_db, session, ids)
    after = CombinedFleetReport(NOW + timedelta(minutes=1), (), question_outcomes=rows)
    digest = combined_hook_digest(after, prior)
    for request_id, outcome in zip(ids, ("answered (Blue)", "withdrawn", "consumed")):
        assert digest.count(f"request {request_id} no longer waiting: {outcome}") == 1
    assert (
        combined_hook_digest(replace(after, question_outcomes=()), after.fingerprint())
        == ""
    )
    assert read_questions(test_db, session) == ()


def _named_question(test_db, monkeypatch, *, project_less):
    from contextlib import contextmanager
    from yoke_core.domain.actors import seed_human_actor

    _project(test_db)
    session = "named-question-worker"
    seed_session(test_db, session, launch_origin="yoke")
    recipient = seed_human_actor(test_db, name="Question Recipient")
    org = test_db.execute(
        "SELECT org_id FROM projects WHERE id=%s", (PROJECT_YOKE,)
    ).fetchone()[0]
    seed_org_role(test_db, actor_id=1, org_id=org, role_name="admin")
    seed_org_role(test_db, actor_id=recipient, org_id=org, role_name="viewer")
    if project_less:
        test_db.execute(
            "UPDATE harness_sessions SET project_id=NULL, org_id=%s WHERE session_id=%s",
            (org, session),
        )
        test_db.commit()

    @contextmanager
    def connection():
        yield test_db

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", connection)
    payload = {"key": "choose", "question": "Which color?", "to": [str(recipient)]}
    if not project_less:
        payload["project"] = str(PROJECT_YOKE)
    filed = handle_ask(_call("decision_requests.ask", session, payload))
    assert filed.primary_success, filed.error
    return session, recipient, org, filed.result_payload["request"]


def test_named_recipient_sees_and_answers_and_asker_gets_mail(test_db, monkeypatch):
    import pytest

    session, recipient, _, row = _named_question(
        test_db, monkeypatch, project_less=False
    )
    waiting = inbox_for_actor(
        test_db, actor_id=recipient, project_ids=[PROJECT_YOKE], include_read=False
    )
    assert row["id"] in [q["id"] for q in waiting["needs_decision"]]
    owner = inbox_for_actor(
        test_db, actor_id=1, project_ids=[PROJECT_YOKE], include_read=False
    )
    assert row["id"] not in [q["id"] for q in owner["needs_decision"]]
    with pytest.raises(PermissionError):
        resolve_decision_request(
            test_db, row["id"], actor_id=1, action="freeform", note="Blue"
        )
    from yoke_core.domain.session_message_service import send_message
    from yoke_core.domain.session_message_types import SessionMessageError
    from yoke_contracts.session_control.models import RecipientSelector

    with pytest.raises(SessionMessageError) as denied:
        send_message(
            test_db,
            actor_id=recipient,
            sender_session_id=None,
            selector=RecipientSelector(session_ids=[session]),
            body="Ordinary message",
        )
    assert denied.value.code == "unauthorized_target"
    answered = resolve_decision_request(
        test_db, row["id"], actor_id=recipient, action="freeform", note="Blue"
    )
    assert "reason" not in answered["subject_context"]["answer_delivery"], answered
    assert _recipients(test_db, f"operator-question-answer:{row['id']}") == [session]


def test_project_less_question_reaches_org_only_member(test_db, monkeypatch):
    from yoke_core.domain.handlers.decision_request_get import (
        handle_decision_request_get,
    )
    from yoke_core.domain.actors import seed_human_actor

    session, recipient, org, row = _named_question(
        test_db, monkeypatch, project_less=True
    )
    assert row["project_id"] is None and row["org_id"] == org
    waiting = inbox_for_actor(
        test_db, actor_id=recipient, project_ids=[PROJECT_YOKE], include_read=False
    )
    assert row["id"] in [q["id"] for q in waiting["needs_decision"]]
    outsider = seed_human_actor(test_db, name="Outside Recipient")
    call = _call("decision_requests.get", session, {"request_id": row["id"]})
    call.actor.actor_id = str(outsider)
    hidden = handle_decision_request_get(call)
    assert not hidden.primary_success and hidden.error.code == "not_found"
    answered = resolve_decision_request(
        test_db, row["id"], actor_id=recipient, action="freeform", note="Blue"
    )
    assert "reason" not in answered["subject_context"]["answer_delivery"], answered
    assert _recipients(test_db, f"operator-question-answer:{row['id']}") == [session]


def test_project_less_question_without_audience_refuses(test_db, monkeypatch):
    from contextlib import contextmanager

    _project(test_db)
    session = "unscoped-question-worker"
    seed_session(test_db, session, launch_origin="yoke")
    org = test_db.execute(
        "SELECT org_id FROM projects WHERE id=%s", (PROJECT_YOKE,)
    ).fetchone()[0]
    test_db.execute(
        "UPDATE harness_sessions SET project_id=NULL, org_id=%s WHERE session_id=%s",
        (org, session),
    )
    test_db.commit()

    @contextmanager
    def connection():
        yield test_db

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", connection)
    result = handle_ask(
        _call("decision_requests.ask", session, {"key": "choose", "question": "Q"})
    )
    assert not result.primary_success
    assert "operator_question_audience_required" in result.error.message
