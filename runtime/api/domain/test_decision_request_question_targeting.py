"""Operator questions target visible subjects and live named audiences."""

from unittest.mock import Mock

import pytest

from runtime.api.domain.decision_request_operator_question_test_support import (
    conn as conn,
    filing,
)
from yoke_core.domain import audiences
from yoke_core.domain.decision_request_question_filing import file_question
from yoke_core.domain.decision_request_question_target import question_target
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.handlers.decision_request_questions import QuestionAskRequest
from yoke_core.domain.steering_fleet_report_questions import read_questions


def target(conn, **kwargs):
    return question_target(
        conn,
        QuestionAskRequest(key="choose", question="Which color?", **kwargs),
        {"session_id": "worker", "project_id": 10},
        1,
    )


def seed_members(conn):
    conn.execute("INSERT INTO actor_org_roles VALUES (1, 1, 4, 'now')")
    conn.execute("INSERT INTO actor_org_roles VALUES (3, 1, 4, 'now')")


def file_target(conn, **kwargs):
    selected = target(conn, **kwargs)
    item_id = selected.pop("item_id")
    return file_question(
        conn,
        **filing(
            **selected,
            subject_context={
                "question": "Which color?",
                **({"item_id": item_id} if item_id else {}),
            },
        ),
    )[0]


def test_report_includes_project_less_question_addressed_to_viewer(conn):
    seed_members(conn)
    row = file_target(conn, to=["3"])
    assert row["project_id"] is None and row["org_id"] == 1
    assert read_questions(conn, "steering") == ()
    conn.execute("UPDATE harness_sessions SET actor_id=3 WHERE session_id='steering'")
    assert [q.request_id for q in read_questions(conn, "steering")] == [row["id"]]


def test_named_audience_question_uses_its_live_members(conn, monkeypatch):
    seed_members(conn)
    audience = audiences.create_audience(
        conn,
        org_id=1,
        name="Reviewers",
        rules=[{"scope_kind": "org", "scope_id": 1, "role_name": "viewer"}],
    )
    row = file_target(conn, audience="Reviewers")
    assert row["audience_id"] == audience
    assert not audiences.includes_actor(conn, audience, 2)
    conn.execute("INSERT INTO actor_org_roles VALUES (2, 1, 4, 'now')")
    assert audiences.includes_actor(conn, audience, 2)
    monkeypatch.setattr(
        "yoke_core.domain.session_message_service.send_message",
        Mock(return_value={"message_id": "answer"}),
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_explicit_wake.mark_explicit_stopped_wake", Mock()
    )
    assert (
        resolve_decision_request(
            conn, row["id"], actor_id=2, action="freeform", note="Blue"
        )["status"]
        == "resolved"
    )


def test_item_need_not_be_held_but_must_match_project(conn):
    conn.execute(
        "INSERT INTO items (id, project_id, project_sequence, title, status, workflow_id, workflow_version_id) VALUES (12, 10, 12, 'Color', 'idea', 'issue', 1)"
    )
    row = file_target(conn, item="YOK-12")
    assert row["subject_context"]["item_id"] == 12
    conn.execute("INSERT INTO projects VALUES (20, 'other', 'Other', 'OTH', 1, 'now')")
    conn.execute("INSERT INTO actor_project_roles VALUES (1, 20, 4, 'now')")
    with pytest.raises(ValueError, match="another project"):
        target(conn, item="YOK-12", project="other")


def test_other_project_requires_visibility(conn):
    conn.execute("INSERT INTO projects VALUES (20, 'other', 'Other', 'OTH', 1, 'now')")
    with pytest.raises((ValueError, LookupError)):
        target(conn, project="other")
    conn.execute("INSERT INTO actor_project_roles VALUES (1, 20, 4, 'now')")
    assert target(conn, project="other")["project_id"] == 20
    conn.execute(
        "UPDATE harness_sessions SET project_id=NULL WHERE session_id='worker'"
    )
    assert file_target(conn, project="other")["project_id"] == 20


def test_project_less_without_audience_refuses(conn):
    with pytest.raises(ValueError, match="operator_question_audience_required"):
        question_target(
            conn,
            QuestionAskRequest(key="choose", question="Q"),
            {"project_id": None},
            1,
        )


def test_target_refuses_ambiguous_org_and_invalid_recipient(conn):
    seed_members(conn)
    conn.execute("INSERT INTO organizations VALUES (2, 'other', 'Other', 'now')")
    for actor in (1, 3):
        conn.execute("INSERT INTO actor_org_roles VALUES (?, 2, 4, 'now')", (actor,))
    with pytest.raises(ValueError, match="operator_question_org_ambiguous"):
        target(conn, to=["3"])
    with pytest.raises(ValueError, match="actor_recipient_not_found"):
        target(conn, to=["999"])
    with pytest.raises(ValueError, match="choose --to or --audience"):
        target(conn, to=["3"], audience="Reviewers")


def test_audience_scope_and_rules_are_required(conn):
    seed_members(conn)
    audience_id = audiences.create_audience(
        conn,
        project_id=10,
        name="Empty",
        rules=[{"scope_kind": "actor", "scope_id": 3}],
    )
    conn.execute("DELETE FROM audience_rules WHERE audience_id=?", (audience_id,))
    with pytest.raises(ValueError, match="empty_audience"):
        target(conn, project="yoke", audience="Empty")
    with pytest.raises(ValueError, match="missing or ambiguous"):
        target(conn, audience="Empty")


@pytest.mark.parametrize(
    "selector", [{"session_ids": ["one", "two"]}, {"universe": True}]
)
def test_engine_answers_require_one_exact_session(conn, selector):
    from yoke_contracts.session_control.models import RecipientSelector
    from yoke_core.domain.session_message_service import send_message
    from yoke_core.domain.session_message_types import SessionMessageError

    with pytest.raises(SessionMessageError) as refused:
        send_message(
            conn,
            actor_id=1,
            sender_session_id=None,
            engine_sender=True,
            selector=RecipientSelector(**selector),
            body="Answer",
        )
    assert refused.value.code == "engine_message_target_invalid"
