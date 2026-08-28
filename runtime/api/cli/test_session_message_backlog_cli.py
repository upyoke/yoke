"""CLI teaching and request shape for unacknowledged Fleet messages."""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters import session_control_messages as messages


@pytest.fixture(autouse=True)
def _top_level_execution(monkeypatch) -> None:
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: False)


def test_default_list_dispatches_the_unacknowledged_union_filter(monkeypatch) -> None:
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(messages, "dispatch_and_emit", _dispatch)

    assert messages.session_message_list(["--recipient-session", "session-2"]) == 0
    assert captured["payload"] == {
        "state": "unacknowledged",
        "session_id": "session-2",
        "limit": 50,
    }


def test_message_help_teaches_the_complete_backlog_filter(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        messages.session_message_list(["--help"])

    assert exit_info.value.code == 0
    rendered = capsys.readouterr().out
    normalized = " ".join(rendered.split())
    assert (
        "defaults to unacknowledged, which includes pending and injected" in normalized
    )
    assert "--state unacknowledged" in rendered
