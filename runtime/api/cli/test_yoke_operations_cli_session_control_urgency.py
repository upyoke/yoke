"""Retired send-urgency knobs are gone from fleet message send."""

from __future__ import annotations

import io
import sys

from yoke_cli.commands.adapters import session_control_messages as messages


def test_say_send_omits_retired_urgency_fields(monkeypatch) -> None:
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(messages, "dispatch_and_emit", _dispatch)
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("act now"))
    assert messages.say(["--stdin", "--session", "session-1"]) == 0
    assert "urgent" not in captured["payload"]
    assert "wake_after_seconds" not in captured["payload"]


def test_say_rejects_retired_urgent_flag(capsys) -> None:
    code = messages.say(["--stdin", "--session", "session-1", "--urgent"])
    assert code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_say_rejects_retired_wake_after_seconds_flag(capsys) -> None:
    code = messages.say(
        ["--stdin", "--session", "session-1", "--wake-after-seconds", "30"]
    )
    assert code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
