"""CLI request shape for human Fleet recipients."""

from __future__ import annotations

import io
import sys

from yoke_cli.commands.adapters import session_control_messages as messages


def test_say_actor_anchor_and_cli_sender_surface(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(
        messages, "dispatch_and_emit", lambda **kwargs: captured.update(kwargs) or 0
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("Read the message."))

    assert messages.say(["--stdin", "--actor", "ben"]) == 0
    assert captured["function_id"] == "session_control.message.send"
    assert captured["payload"] == {
        "selector": {"actors": ["ben"]},
        "body": "Read the message.",
        "sender_surface": "cli",
    }


def test_say_help_names_human_actor_addressing(capsys) -> None:
    try:
        messages.say(["--help"])
    except SystemExit as raised:
        assert raised.code == 0
    rendered = capsys.readouterr().out
    assert "--actor ACTOR" in rendered
    assert "Human organization member" in rendered
    assert "yoke say --actor ben --stdin" in rendered


def test_preview_output_lists_human_recipients() -> None:
    response = type(
        "Response",
        (),
        {
            "result": {
                "recipients": [],
                "actor_recipients": [{"actor_id": 11, "label": "ben", "kind": "human"}],
                "recipient_count": 1,
            }
        },
    )()
    output = io.StringIO()

    messages.write_message_result(response, output, io.StringIO())

    rendered = output.getvalue()
    assert "RECIPIENT" in rendered
    assert "ben" in rendered
    assert "human inbox" in rendered


def _steering_recipient(**overrides) -> dict:
    recipient = {
        "kind": "steering",
        "state": "awaiting_seat",
        "scope": {"project_id": 1},
        "scope_label": "alpha",
        "project_id": 1,
        "sender_item_id": 101,
        "session_id": None,
        "label": "steering seat",
        "executor_surface": "steering seat",
        "messageability": {"messageable": False, "reason": "awaiting_seat"},
        "delivered_at": None,
        "acknowledged_at": None,
        "summary": "queued for the steering seat covering alpha; no live seat "
        "covers it yet, and the next covering acquire drains it",
    }
    recipient.update(overrides)
    return recipient


def _rendered(result: dict) -> str:
    response = type("Response", (), {"result": result})()
    output = io.StringIO()
    messages.write_message_result(response, output, io.StringIO())
    return output.getvalue()


def test_a_queued_role_send_says_which_seat_it_waits_for() -> None:
    """Zero session recipients must not read as a message that went nowhere."""
    rendered = _rendered(
        {
            "message_id": "m-1",
            "recipients": [],
            "actor_recipients": [],
            "recipient_count": 1,
            "steering_recipient": _steering_recipient(),
        }
    )

    assert "queued for the steering seat covering alpha" in rendered
    assert "steering seat" in rendered
    assert "awaiting seat" in rendered


def test_a_seated_role_send_names_the_holding_seat() -> None:
    rendered = _rendered(
        {
            "message_id": "m-2",
            "recipients": [],
            "actor_recipients": [],
            "recipient_count": 1,
            "steering_recipient": _steering_recipient(
                state="delivered",
                session_id="s-seat",
                messageability={"messageable": True},
                summary="delivered to the steering seat covering alpha (s-seat)",
            ),
        }
    )

    assert "delivered to the steering seat covering alpha (s-seat)" in rendered
    assert "s-seat" in rendered


def test_message_detail_carries_the_role_recipient_state() -> None:
    rendered = _rendered(
        {
            "message": {
                "message_id": "m-3",
                "recipients": [],
                "actor_recipients": [],
                "sender_actor_id": 10,
                "created_at": "2026-08-22T16:00:00Z",
                "expires_at": "2026-08-23T16:00:00Z",
                "body": "Blocked on the schema converge step.",
                "steering_recipient": _steering_recipient(),
            }
        }
    )

    assert "Steering" in rendered
    assert "queued for the steering seat covering alpha" in rendered
    assert "Recipients     1" in rendered
    assert "State          awaiting seat" in rendered
