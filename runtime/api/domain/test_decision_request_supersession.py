"""Replacement keeps answers as linked history and removes current decisions."""

from unittest.mock import Mock

import pytest

from runtime.api.domain.decision_request_operator_question_test_support import (
    conn as conn,
    filing,
)
from yoke_core.domain.decision_request_question_filing import (
    file_question,
    list_questions,
)
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
    withdraw_decision_request,
)
from yoke_core.domain.decision_request_rows import request_row
from yoke_core.domain.steering_fleet_report_questions import (
    question_states,
    read_questions,
    outcome_lines,
)


@pytest.mark.parametrize("resolved", [False, True])
def test_replacement_preserves_resolution_and_is_only_history(
    conn, monkeypatch, resolved
):
    monkeypatch.setattr(
        "yoke_core.domain.session_message_service.send_message",
        Mock(return_value={"message_id": "answer-message"}),
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_explicit_wake.mark_explicit_stopped_wake", Mock()
    )
    old, _ = file_question(conn, **filing())
    if resolved:
        old = resolve_decision_request(
            conn,
            old["id"],
            actor_id=2,
            session_id="steering",
            action="freeform",
            note="Original answer",
        )
    new, created = file_question(
        conn, replaces=old["id"], **filing(subject_context={"question": "Revised?"})
    )
    prior = request_row(conn, old["id"])
    assert created and new["status"] == "pending" and new["id"] != old["id"]
    assert prior["status"] == "superseded"
    assert prior["superseded_by_request_id"] == new["id"]
    for field in (
        "resolution_action",
        "resolution_note",
        "resolution_actor_id",
        "resolved_at",
        "decisions",
    ):
        assert prior[field] == old[field]
    assert [q["id"] for q in list_questions(conn, "worker", "superseded")] == [
        old["id"]
    ]
    if resolved:
        assert (
            list_questions(conn, "worker", "superseded")[0]["answer"]
            == "Original answer"
        )
    assert question_states(conn, "steering", include_resolved=True) == {
        new["id"]: "pending"
    }
    history = read_questions(conn, "steering", (old["id"],))
    assert f"superseded by request {new['id']}" in "\n".join(outcome_lines(history))
    assert [q.request_id for q in read_questions(conn, "steering")] == [new["id"]]


@pytest.mark.parametrize("state", ["withdrawn", "superseded"])
def test_ended_requests_cannot_be_replaced(conn, state):
    old, _ = file_question(conn, **filing())
    if state == "withdrawn":
        withdraw_decision_request(
            conn, old["id"], actor_id=1, session_id="worker", reason="Cancelled"
        )
    else:
        file_question(conn, replaces=old["id"], **filing())
    with pytest.raises(
        ValueError,
        match="operator_question_replace_invalid: replace a pending or resolved question from the same requesting session",
    ):
        file_question(conn, replaces=old["id"], **filing())


@pytest.mark.parametrize("resolved", [False, True])
def test_failed_replacement_rolls_back_and_other_requester_refuses(conn, resolved):
    old, _ = file_question(conn, **filing())
    if resolved:
        # Preserve a real recorded resolution without attempting external mail.
        conn.execute(
            "UPDATE decision_requests SET status='resolved', resolution_action='blue', resolution_actor_id=2 WHERE id=?",
            (old["id"],),
        )
        conn.commit()
    for overrides, reason in (
        ({"subject_context": {"question": ""}}, "operator_question_invalid"),
        (
            {"requesting_session_id": "other", "subject_key": "other:choose"},
            "operator_question_replace_invalid",
        ),
    ):
        with pytest.raises(ValueError, match=reason):
            file_question(conn, replaces=old["id"], **filing(**overrides))
        assert request_row(conn, old["id"])["status"] == (
            "resolved" if resolved else "pending"
        )
        assert request_row(conn, old["id"])["superseded_by_request_id"] is None
        assert len(list_questions(conn, "worker")) == 1
