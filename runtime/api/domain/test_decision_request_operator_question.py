"""Non-gating questions keep their identity, answers and delivery evidence."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from runtime.api.domain.decision_request_test_support import decision_request_connection
from yoke_core.domain.decision_request_operator_question import validate, subject_ended
from yoke_core.domain.decision_request_question_filing import (
    file_question,
    list_questions,
)
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
    withdraw_decision_request,
)
from yoke_core.domain.decision_request_rows import request_row
from yoke_core.domain.decision_requests import RoleAuthority


@pytest.fixture
def conn():
    with decision_request_connection() as value:
        value.executescript("""
            CREATE TABLE harness_sessions (
                session_id TEXT PRIMARY KEY, project_id INTEGER, actor_id INTEGER,
                executor TEXT, ended_at TEXT, terminated_at TEXT
            );
            CREATE TABLE work_claims (
                id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
                scope TEXT, released_at TEXT
            );
            INSERT INTO harness_sessions VALUES ('worker', 10, 1, 'codex', NULL, NULL);
            INSERT INTO harness_sessions VALUES ('other', 10, 1, 'cursor', NULL, NULL);
            INSERT INTO harness_sessions VALUES ('steering', 10, 2, 'claude-code', NULL, NULL);
        """)
        yield value


def filing(**overrides):
    return {
        "kind": "operator_question",
        "subject_type": "session_question",
        "subject_key": "worker:choose",
        "project_id": 10,
        "requesting_session_id": "worker",
        "originator_actor_id": 1,
        "session_id": "worker",
        "role_authorities": [RoleAuthority("project", 10, "owner")],
        "subject_context": {
            "question": "Which color?",
            "options": [
                {"id": "blue", "label": "Blue"},
                {"id": "green", "label": "Green"},
            ],
            "recommended_option": "blue",
        },
        **overrides,
    }


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"question": " "},
        {"question": "q" * 2001},
        {"question": "q", "context": "c" * 8001},
        {"question": "q", "allow_freeform": False},
        {"question": "q", "allow_freeform": 1},
        {"question": "q", "options": [{"id": "blue", "label": "B"}] * 2},
        {"question": "q", "recommended_option": "absent"},
        {"question": "q", "options": [{"id": "UPPER", "label": "B"}]},
        {"question": "q", "options": [{"id": "blue", "label": "B" * 81}]},
        {
            "question": "q",
            "options": [{"id": "blue", "label": "B", "detail": "d" * 501}],
        },
        {"question": "q", "options": [{"id": "freeform", "label": "Reserved"}]},
        {
            "question": "q",
            "options": [{"id": f"o-{n}", "label": "B"} for n in range(9)],
        },
    ],
)
def test_invalid_context_names_reason_and_recovery(context):
    with pytest.raises(ValueError, match="operator_question_invalid") as exc:
        validate(context)
    assert "retry decision-requests ask" in str(exc.value)


def test_creation_idempotency_actions_and_session_history(conn):
    row, created = file_question(conn, **filing())
    again, repeated = file_question(conn, **filing())
    other, _ = file_question(
        conn, **filing(requesting_session_id="other", subject_key="other:choose")
    )
    assert created and not repeated and row["id"] == again["id"]
    assert row["actions"] == ["blue", "green", "freeform"]
    assert row["requesting_session_id"] == "worker"
    assert row["approval_mode"] == "any"
    assert [q["id"] for q in list_questions(conn, "worker")] == [row["id"]]
    assert [q["id"] for q in list_questions(conn, "other")] == [other["id"]]


def test_no_options_defaults_to_freeform(conn):
    row, _ = file_question(conn, **filing(subject_context={"question": "What next?"}))
    assert row["actions"] == ["freeform"]


@pytest.mark.parametrize(
    "action,note", [("blue", "Proceed"), ("freeform", "Use violet")]
)
def test_answers_record_actor_session_and_send_once(conn, monkeypatch, action, note):
    sender = Mock(return_value={"message_id": "answer-message"})
    monkeypatch.setattr("yoke_core.domain.session_message_service.send_message", sender)
    monkeypatch.setattr(
        "yoke_core.domain.session_explicit_wake.mark_explicit_stopped_wake", Mock()
    )
    row, _ = file_question(conn, **filing())
    answered = resolve_decision_request(
        conn, row["id"], actor_id=2, session_id="steering", action=action, note=note
    )
    assert answered["status"] == "resolved"
    assert answered["decisions"][0]["actor_id"] == 2
    assert answered["decisions"][0]["decided_session_id"] == "steering"
    assert answered["resolution_note"] == note
    assert list_questions(conn, "worker", "pending") == []
    assert sender.call_args.kwargs["selector"].session_ids == ["worker"]
    assert note in sender.call_args.kwargs["body"]
    from yoke_core.domain.decision_request_operator_answer_delivery import (
        deliver_answer,
    )

    deliver_answer(conn, answered)
    assert sender.call_count == 1


def test_unknown_and_empty_answers_refuse(conn):
    row, _ = file_question(conn, **filing())
    for action, note in (("unknown", None), ("freeform", " ")):
        with pytest.raises(ValueError):
            resolve_decision_request(
                conn, row["id"], actor_id=2, action=action, note=note
            )
    assert request_row(conn, row["id"])["status"] == "pending"


def test_delivery_falls_back_only_to_current_holder(conn, monkeypatch):
    sender = Mock(return_value={"message_id": "holder-message"})
    monkeypatch.setattr("yoke_core.domain.session_message_service.send_message", sender)
    monkeypatch.setattr(
        "yoke_core.domain.session_explicit_wake.mark_explicit_stopped_wake", Mock()
    )
    row, _ = file_question(conn, **filing())
    context = row["subject_context"] | {"item_id": 12}
    conn.execute(
        "UPDATE decision_requests SET subject_context=? WHERE id=?",
        (json.dumps(context), row["id"]),
    )
    conn.execute(
        "UPDATE harness_sessions SET ended_at='ended' WHERE session_id='worker'"
    )
    conn.execute(
        "INSERT INTO work_claims VALUES (1, 'other', 'item', ?, NULL)",
        (json.dumps({"item_id": 12}),),
    )
    answered = resolve_decision_request(conn, row["id"], actor_id=2, action="blue")
    assert sender.call_args.kwargs["selector"].session_ids == ["other"]
    assert (
        answered["subject_context"]["answer_delivery"]["message_id"] == "holder-message"
    )


@pytest.mark.parametrize("failure", [False, True])
def test_missing_recipient_or_send_failure_keeps_answer_and_named_reason(
    conn, monkeypatch, failure
):
    row, _ = file_question(conn, **filing())
    if failure:
        monkeypatch.setattr(
            "yoke_core.domain.session_message_service.send_message",
            Mock(side_effect=RuntimeError("offline")),
        )
    else:
        conn.execute(
            "UPDATE harness_sessions SET ended_at='ended' WHERE session_id='worker'"
        )
    answered = resolve_decision_request(conn, row["id"], actor_id=2, action="blue")
    assert answered["status"] == "resolved"
    assert (
        answered["subject_context"]["answer_delivery"]["reason"]
        == "operator_question_undelivered"
    )
    assert list_questions(conn, "worker")[0]["resolution_action"] == "blue"


def test_requester_can_cancel_without_ending_subject(conn):
    row, _ = file_question(conn, **filing())
    cancelled = withdraw_decision_request(
        conn, row["id"], actor_id=1, session_id="worker", reason="No longer needed"
    )
    assert cancelled["status"] == "withdrawn"
    assert cancelled["withdrawal_reason"] == "No longer needed"


def test_other_session_cannot_cancel(conn, monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.session_steering_authority.covering_session_seat",
        lambda *a, **k: None,
    )
    row, _ = file_question(conn, **filing())
    with pytest.raises(PermissionError, match="operator_question_cancel_forbidden"):
        withdraw_decision_request(
            conn, row["id"], actor_id=1, session_id="other", reason="Cancel"
        )
    assert request_row(conn, row["id"])["status"] == "pending"


def test_steering_can_cancel(conn, monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.session_steering_authority.covering_session_seat",
        lambda *a, **k: {"id": 1},
    )
    row, _ = file_question(conn, **filing())
    cancelled = withdraw_decision_request(
        conn, row["id"], actor_id=2, session_id="steering", reason="Direction changed"
    )
    assert cancelled["status"] == "withdrawn"


def test_replace_is_atomic_and_names_replacement(conn):
    old, _ = file_question(conn, **filing())
    new, _ = file_question(
        conn,
        replaces=old["id"],
        **filing(subject_context={"question": "New question?"}),
    )
    assert new["id"] != old["id"]
    prior = request_row(conn, old["id"])
    assert prior["status"] == "withdrawn"
    assert str(new["id"]) in prior["withdrawal_reason"]
    assert [q["id"] for q in list_questions(conn, "worker", "pending")] == [new["id"]]


def test_failed_replace_preserves_original(conn):
    old, _ = file_question(conn, **filing())
    with pytest.raises(ValueError, match="operator_question_invalid"):
        file_question(
            conn, replaces=old["id"], **filing(subject_context={"question": ""})
        )
    assert request_row(conn, old["id"])["status"] == "pending"
    with pytest.raises(ValueError, match="operator_question_replace_invalid"):
        file_question(
            conn,
            replaces=old["id"],
            **filing(requesting_session_id="other", subject_key="other:choose"),
        )
    assert len(list_questions(conn, "worker")) == 1


def test_ended_unattached_session_withdraws_question(conn):
    row, _ = file_question(conn, **filing())
    assert not subject_ended(conn, row, None)[0]
    conn.execute(
        "UPDATE harness_sessions SET ended_at='ended' WHERE session_id='worker'"
    )
    assert subject_ended(conn, row, None)[0]
    from yoke_core.domain.decision_request_resolution import withdraw_for_ended_subject

    assert (
        withdraw_for_ended_subject(conn, row["id"], reason="Session ended")["status"]
        == "withdrawn"
    )


def test_questions_have_no_gate_effect_or_gate_subject(conn):
    from yoke_core.domain.decision_request_contract import DECISION_KINDS
    from yoke_core.domain.decision_request_subject_effect import _SUBJECT_EFFECTS
    from yoke_core.domain.actor_decision_queue import pending_requests_for_actor

    row, _ = file_question(conn, **filing())
    assert DECISION_KINDS["operator_question"].subject_type == "session_question"
    assert "operator_question" not in _SUBJECT_EFFECTS
    assert pending_requests_for_actor(conn, 2)[0]["id"] == row["id"]
    assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 0


def test_report_orders_questions_drops_answered_and_fingerprints_content(
    conn, monkeypatch
):
    from yoke_core.domain.steering_fleet_report_questions import (
        read_questions,
        question_lines,
    )
    from yoke_core.domain.steering_fleet_report_fingerprint import question_fingerprint

    first, _ = file_question(conn, **filing(created_at="2026-01-01T00:00:00Z"))
    second, _ = file_question(
        conn, **filing(subject_key="worker:later", created_at="2026-01-02T00:00:00Z")
    )
    rows = read_questions(conn, [10])
    assert [q.request_id for q in rows] == [first["id"], second["id"]]
    assert "Questions waiting on you" in "\n".join(
        question_lines(rows, "2026-01-03T00:00:00Z")
    )
    before = question_fingerprint(rows)
    assert before == question_fingerprint(read_questions(conn, [10]))
    withdraw_decision_request(
        conn, first["id"], actor_id=1, session_id="worker", reason="Cancelled"
    )
    assert [q.request_id for q in read_questions(conn, [10])] == [second["id"]]
