"""The routine read of one message, and what it says it held back."""

from __future__ import annotations

from yoke_contracts.read_detail import DETAIL_FULL, DETAIL_SUMMARY
from yoke_contracts.session_control.message_projection import (
    ATTEMPTS_WITHHELD_KEY,
    ATTEMPTS_WITHHELD_READ_KEY,
    ROUTINE_ATTEMPT_ROWS,
    project_message,
    unknown_message_fields,
)


def _message(attempt_count: int) -> dict:
    return {
        "message_id": "m-1",
        "body": "the prose someone wrote",
        "sender_session_id": "s-1",
        "acknowledgement_command": "yoke messages acknowledge m-1",
        "attempts": [{"attempt_id": f"a-{n}"} for n in range(attempt_count)],
    }


def test_routine_read_serves_the_whole_body() -> None:
    projected = project_message(_message(0), detail=DETAIL_SUMMARY)
    assert projected["body"] == "the prose someone wrote"


def test_routine_read_keeps_a_short_attempt_log_whole() -> None:
    message = _message(ROUTINE_ATTEMPT_ROWS)
    projected = project_message(message, detail=DETAIL_SUMMARY)
    assert len(projected["attempts"]) == ROUTINE_ATTEMPT_ROWS
    assert ATTEMPTS_WITHHELD_KEY not in projected


def test_routine_read_bounds_a_long_attempt_log_and_names_the_rest() -> None:
    message = _message(ROUTINE_ATTEMPT_ROWS + 70)
    projected = project_message(message, detail=DETAIL_SUMMARY)
    assert len(projected["attempts"]) == ROUTINE_ATTEMPT_ROWS
    assert projected[ATTEMPTS_WITHHELD_KEY] == 70
    assert projected[ATTEMPTS_WITHHELD_READ_KEY] == "yoke messages get m-1 --full"


def test_bounded_read_keeps_the_most_recent_attempts() -> None:
    message = _message(ROUTINE_ATTEMPT_ROWS + 3)
    projected = project_message(message, detail=DETAIL_SUMMARY)
    kept = [attempt["attempt_id"] for attempt in projected["attempts"]]
    assert kept[-1] == f"a-{ROUTINE_ATTEMPT_ROWS + 2}"


def test_full_detail_serves_every_attempt() -> None:
    message = _message(ROUTINE_ATTEMPT_ROWS + 70)
    projected = project_message(message, detail=DETAIL_FULL)
    assert len(projected["attempts"]) == ROUTINE_ATTEMPT_ROWS + 70
    assert ATTEMPTS_WITHHELD_KEY not in projected


def test_named_fields_serve_exactly_those_fields() -> None:
    message = _message(ROUTINE_ATTEMPT_ROWS + 70)
    projected = project_message(message, fields=("body",))
    assert projected == {"body": "the prose someone wrote"}


def test_named_fields_win_over_the_attempt_bound() -> None:
    """A caller asking for attempts asked for them; do not re-bound."""
    message = _message(ROUTINE_ATTEMPT_ROWS + 70)
    projected = project_message(message, fields=("attempts",), detail=DETAIL_SUMMARY)
    assert len(projected["attempts"]) == ROUTINE_ATTEMPT_ROWS + 70
    assert ATTEMPTS_WITHHELD_KEY not in projected


def test_unknown_fields_are_reported_for_the_refusal() -> None:
    assert unknown_message_fields(_message(0), ("body", "nope")) == ["nope"]
    assert unknown_message_fields(_message(0), ("body",)) == []


def test_nonrecipient_reads_recipient_states_without_empty_envelope_fields(monkeypatch):
    import io
    from types import SimpleNamespace

    import pytest

    from yoke_cli.commands.adapters.session_control_common import write_message_detail_result
    from yoke_core.domain import session_message_queries as queries
    from yoke_core.domain.handlers.session_messages_common import readable_json_message
    from yoke_core.domain.session_message_types import SessionMessageError

    recipients = [{"session_id": "recipient", "state": "acknowledged"}]
    details = {**_message(0), "recipients": recipients, "actor_recipients": []}
    monkeypatch.setattr(queries, "message_details", lambda *_: details)
    monkeypatch.setattr(queries, "message_visible", lambda *_, **__: True)
    monkeypatch.setattr(queries, "project_due_receipts", lambda *_, **__: None)
    caller = {"message_id": "m-1", "actor_id": 7, "session_id": "sender"}

    with pytest.raises(SessionMessageError) as raised:
        queries.get_message(None, **caller, fields=("state",))
    assert raised.value.code == "message_field_unknown"
    assert "recipients" in str(raised.value)
    result = readable_json_message(
        queries.get_message(None, **caller, fields=("recipients",))
    )
    assert result == {"message": {"recipients": recipients}}
    output = io.StringIO()
    write_message_detail_result(SimpleNamespace(result=result), output, io.StringIO())
    assert "acknowledged" in output.getvalue()
    assert "message_id" not in output.getvalue()
    assert "body" not in output.getvalue()
    assert "None" not in output.getvalue()

    recipient = queries.get_message(None, **{**caller, "session_id": "recipient"})
    assert readable_json_message(recipient)["state"] == "acknowledged"
    details["actor_recipients"] = [{"actor_id": 7, "state": "pending"}]
    actor_recipient = queries.get_message(None, **caller)
    assert readable_json_message(actor_recipient)["state"] == "pending"
