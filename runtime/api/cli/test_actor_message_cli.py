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
                "actor_recipients": [
                    {"actor_id": 11, "label": "ben", "kind": "human"}
                ],
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
