"""CLI urgency knobs for fleet message send."""

from __future__ import annotations

import io
import sys

from yoke_cli.commands.adapters import session_control_messages as messages


def test_say_urgent_send_puts_the_flag_on_the_payload(monkeypatch) -> None:
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(messages, "dispatch_and_emit", _dispatch)
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("act now"))
    assert messages.say(["--stdin", "--session", "session-1", "--urgent"]) == 0
    assert captured["payload"]["urgent"] is True
    assert "wake_after_seconds" not in captured["payload"]


def test_say_wake_after_seconds_puts_the_delay_on_the_payload(monkeypatch) -> None:
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(messages, "dispatch_and_emit", _dispatch)
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("act soon"))
    assert (
        messages.say(
            [
                "--stdin",
                "--session",
                "session-1",
                "--wake-after-seconds",
                "30",
            ]
        )
        == 0
    )
    assert captured["payload"]["wake_after_seconds"] == 30
    assert "urgent" not in captured["payload"]


def test_say_refuses_urgent_together_with_wake_after_seconds(capsys) -> None:
    code = messages.say(
        [
            "--stdin",
            "--session",
            "session-1",
            "--urgent",
            "--wake-after-seconds",
            "30",
        ]
    )
    assert code == 2
    assert "not allowed with argument" in capsys.readouterr().err
