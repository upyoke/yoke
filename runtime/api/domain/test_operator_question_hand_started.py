"""Steering skips questions from other hand-started sessions, never its own.

A hand-started session's operator answers in that session's chat, so the
steering report, hook digest and watcher poll leave its questions out, even
when that session holds a steering seat of its own. The
Inbox and ``decision-requests list`` still show them.
"""

from contextlib import contextmanager

from runtime.api.domain.steering_fleet_report_delivery_test_support import (
    steering_scope as steering_scope,
    NOW,
    STEERING_SESSION,
    PROJECT_ID,
)
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    _project,
    seed_session,
)
from runtime.api.domain.operator_question_integration_test_support import _call
from yoke_core.domain.decision_request_question_filing import file_question
from yoke_core.domain.decision_requests import RoleAuthority
from yoke_core.domain.handlers.decision_request_questions import handle_list
from yoke_core.domain.handlers.steering_report import handle_get
from yoke_core.domain.inbox_read import inbox_for_actor
from yoke_core.domain.steering_fleet_report_compose import CombinedFleetReport
from yoke_core.domain.steering_fleet_report_delivery import steering_report_for_delivery
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest
from yoke_core.domain.steering_fleet_report_questions import read_questions

HAND = "hand-started-desktop"
WORKER = "yoke-launched-worker"
GONE = "session-without-row"


def _ask(conn, session):
    question, _ = file_question(
        conn,
        kind="operator_question",
        subject_type="session_question",
        subject_key=f"{session}:choose",
        requesting_session_id=session,
        session_id=session,
        project_id=PROJECT_ID,
        originator_actor_id=1,
        role_authorities=[RoleAuthority("project", PROJECT_ID, "owner")],
        subject_context={
            "question": f"Which color for {session}?",
            "options": [{"id": "blue", "label": "Blue"}],
        },
    )
    return question["id"]


def _seed_questions(conn):
    _project(conn)
    seed_session(conn, HAND, PROJECT_ID)
    seed_session(conn, WORKER, PROJECT_ID, launch_origin="yoke")
    seed_session(conn, GONE, PROJECT_ID)
    conn.execute("UPDATE harness_sessions SET actor_id=1")
    ids = {
        session: _ask(conn, session)
        for session in (HAND, WORKER, STEERING_SESSION, GONE)
    }
    conn.execute("DELETE FROM harness_sessions WHERE session_id=%s", (GONE,))
    conn.commit()
    return ids


class _Borrowed:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def close(self):
        pass


def test_steering_surfaces_skip_other_hand_started_questions(
    steering_scope, monkeypatch
):
    conn = steering_scope
    ids = _seed_questions(conn)
    # HAND steers elsewhere; holding a steering seat no longer exempts it.
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, "
        "last_heartbeat) VALUES (%s, 'steering', '{\"project_id\": 999}', %s, %s)",
        (HAND, NOW, NOW),
    )
    conn.commit()
    shown = {ids[WORKER], ids[STEERING_SESSION], ids[GONE]}

    report = steering_report_for_delivery(conn, session_id=STEERING_SESSION, now=NOW)
    assert report is not None
    assert f"request {ids[HAND]} " not in report
    for request_id in shown:
        assert f"request {request_id} " in report

    questions = read_questions(conn, STEERING_SESSION)
    assert {row.request_id for row in questions} == shown
    digest = combined_hook_digest(CombinedFleetReport(NOW, (), questions=questions), "")
    assert f"request {ids[HAND]} " not in digest
    for request_id in shown:
        assert f"request {request_id} " in digest

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: _Borrowed(conn))
    poll = handle_get(
        _call("steering.report.get", STEERING_SESSION, {"questions_only": True})
    )
    assert poll.primary_success, poll.error
    assert set(poll.result_payload["question_states"]) == shown


def test_inbox_and_list_still_show_hand_started_question(steering_scope, monkeypatch):
    conn = steering_scope
    ids = _seed_questions(conn)

    waiting = inbox_for_actor(
        conn, actor_id=1, project_ids=[PROJECT_ID], include_read=False
    )
    assert ids[HAND] in [row["id"] for row in waiting["needs_decision"]]

    @contextmanager
    def connection():
        yield conn

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", connection)
    listed = handle_list(_call("decision_requests.list", HAND, {}))
    assert listed.primary_success, listed.error
    assert [q["id"] for q in listed.result_payload["questions"]] == [ids[HAND]]
