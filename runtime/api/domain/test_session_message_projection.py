"""The routine read of one message, and what it says it held back."""

from __future__ import annotations

from yoke_contracts.read_detail import DETAIL_FULL, DETAIL_SUMMARY
from yoke_core.domain.session_message_projection import (
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
