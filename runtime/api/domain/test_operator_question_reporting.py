"""Question polling stays scoped and shares delivery with hook outcomes."""

from datetime import timedelta

from runtime.api.domain.steering_fleet_report_delivery_test_support import (
    steering_scope as steering_scope,
    NOW,
    STEERING_SESSION,
    PLAIN_SESSION,
    PROJECT_ID,
)
from runtime.api.domain.operator_question_integration_test_support import _call
from yoke_core.domain.decision_request_question_filing import file_question
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.decision_requests import RoleAuthority
from yoke_core.domain.handlers.steering_report import handle_get
from yoke_core.domain.steering_fleet_report_delivery import steering_report_for_delivery


class BorrowedConnection:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def close(self):
        pass


def test_light_poll_finds_hook_seen_answer_and_forces_one_outcome(
    steering_scope, monkeypatch
):
    conn = steering_scope
    from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
        _project,
        seed_session,
    )

    _project(conn)
    worker = "question-worker"
    seed_session(conn, worker, launch_origin="yoke")
    conn.execute("UPDATE harness_sessions SET actor_id=1")
    question, _ = file_question(
        conn,
        kind="operator_question",
        subject_type="session_question",
        subject_key=f"{worker}:choose",
        requesting_session_id=worker,
        session_id=worker,
        project_id=PROJECT_ID,
        originator_actor_id=1,
        role_authorities=[RoleAuthority("project", PROJECT_ID, "owner")],
        subject_context={
            "question": "Which color?",
            "options": [{"id": "blue", "label": "Blue"}],
        },
    )
    assert f"request {question['id']}" in steering_report_for_delivery(
        conn,
        session_id=STEERING_SESSION,
        now=NOW,
    )
    resolve_decision_request(
        conn,
        question["id"],
        actor_id=1,
        action="blue",
        session_id=STEERING_SESSION,
    )
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect", lambda: BorrowedConnection(conn)
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_store.utc_now",
        lambda: NOW + timedelta(seconds=10),
    )
    # A new watcher has no local request ids; the hook's saved ids still find the answer.
    poll = handle_get(
        _call("steering.report.get", STEERING_SESSION, {"questions_only": True})
    )
    assert poll.primary_success, poll.error
    assert poll.result_payload["question_states"] == {question["id"]: "resolved"}
    result = handle_get(
        _call(
            "steering.report.get",
            STEERING_SESSION,
            {"deliver": True, "question_change": True},
        )
    )
    assert result.primary_success, result.error
    assert result.result_payload["delivered"]
    assert (
        result.result_payload["digest"].count(
            f"request {question['id']} no longer waiting: answered (Blue)"
        )
        == 1
    )
    again = handle_get(
        _call(
            "steering.report.get",
            STEERING_SESSION,
            {"deliver": True, "question_change": True},
        )
    )
    assert again.result_payload["composition_skipped"]
    assert (
        steering_report_for_delivery(
            conn, session_id=STEERING_SESSION, now=NOW + timedelta(seconds=20)
        )
        is None
    )
    denied = handle_get(
        _call(
            "steering.report.get",
            PLAIN_SESSION,
            {"questions_only": True, "previous_question_ids": [question["id"]]},
        )
    )
    assert not denied.primary_success and denied.error.code == "steering_claim_required"


def test_project_less_questions_filter_viewer_in_report_poll_and_outcomes(
    steering_scope, monkeypatch
):
    from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
        seed_session,
    )
    from yoke_core.domain.steering_fleet_report_compose import compose_held_reports
    from yoke_core.domain.steering_fleet_report_questions import read_questions

    from yoke_core.domain.actors import seed_human_actor

    conn = steering_scope
    recipient = seed_human_actor(conn, name="Question reviewer")
    worker = "organization-question-worker"
    seed_session(conn, worker, launch_origin="yoke")
    org = conn.execute(
        "SELECT org_id FROM projects WHERE id=%s", (PROJECT_ID,)
    ).fetchone()[0]
    question, _ = file_question(
        conn,
        kind="operator_question",
        subject_type="session_question",
        subject_key=f"{worker}:choose",
        requesting_session_id=worker,
        session_id=worker,
        org_id=org,
        originator_actor_id=1,
        named_actor_ids=[recipient],
        subject_context={"question": "Which color?"},
    )
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect", lambda: BorrowedConnection(conn)
    )
    for viewer, expected in ((recipient, {question["id"]: "pending"}), (1, {})):
        conn.execute(
            "UPDATE harness_sessions SET actor_id=%s WHERE session_id=%s",
            (viewer, STEERING_SESSION),
        )
        conn.commit()
        poll = handle_get(
            _call("steering.report.get", STEERING_SESSION, {"questions_only": True})
        )
        assert poll.primary_success, poll.error
        assert poll.result_payload["question_states"] == expected
        report = compose_held_reports(conn, session_id=STEERING_SESSION, now=NOW)
        assert [row.request_id for row in report.questions] == list(expected)
    answered = resolve_decision_request(
        conn, question["id"], actor_id=recipient, action="freeform", note="Blue"
    )
    assert answered["status"] == "resolved"
    assert read_questions(conn, STEERING_SESSION, [question["id"]]) == ()
    conn.execute(
        "UPDATE harness_sessions SET actor_id=%s WHERE session_id=%s",
        (recipient, STEERING_SESSION),
    )
    [outcome] = read_questions(conn, STEERING_SESSION, [question["id"]])
    assert outcome.outcome == "answered (Blue)"
