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


def test_message_help_points_to_the_inbox_doc(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        messages.session_message_list(["--help"])

    assert exit_info.value.code == 0
    rendered = capsys.readouterr().out
    assert ".yoke/docs/sessions/inbox.md" in rendered


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("json_mode", [False, True])
def test_listing_requests_and_prints_complete_bodies_only_when_full(
    monkeypatch, capsys, full, json_mode
):
    import json
    from yoke_cli.transport.output_limit import read_output_scope
    from yoke_contracts.api.function_call import FunctionCallResponse
    from yoke_contracts.read_detail import SUMMARY_EXCERPT_CHARACTERS

    body = "message context\n" * SUMMARY_EXCERPT_CHARACTERS + "END OF BODY"
    calls = []

    def dispatch(request):
        calls.append(request)
        row = {"message_id": "message-example", "sender_session_id": "sender"}
        if request.payload.get("detail") == "full":
            row["body"] = body
        else:
            row["body_excerpt"] = body[:SUMMARY_EXCERPT_CHARACTERS]
        return FunctionCallResponse(
            success=True,
            function="session_control.message.list",
            version="v1",
            result={"messages": [row], "count": 1},
        )

    monkeypatch.setattr("yoke_core.domain.yoke_function_dispatch.dispatch", dispatch)
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.ensure_handlers_loaded", lambda: None
    )
    args = (["--full"] if full else []) + (["--json"] if json_mode else [])
    args += ["--session-id", "reader"]
    with read_output_scope(
        args, "session_control.message.list", ("yoke", "messages", "list")
    ):
        assert messages.session_message_list(args) == 0
    rendered = capsys.readouterr()
    assert not rendered.err
    assert calls[0].payload == {
        "state": "unacknowledged",
        "limit": 50,
        **({"detail": "full"} if full else {}),
    }
    if json_mode:
        row = json.loads(rendered.out)["result"]["messages"][0]
        assert row.get("body") == (body if full else None)
        assert ("body_excerpt" in row) is not full
    elif full:
        assert body in rendered.out
        assert "BODY\n" in rendered.out
        assert (
            "details: yoke messages get message-example --json --full" in rendered.out
        )
    else:
        assert "MESSAGES" in rendered.out
        assert "END OF BODY" not in rendered.out


def test_full_listing_preserves_empty_state():
    import io
    from types import SimpleNamespace
    from yoke_cli.transport.output_limit import read_output_scope

    output = io.StringIO()
    with read_output_scope(["--full"], "session_control.message.list"):
        messages.write_message_result(
            SimpleNamespace(result={"messages": []}), output, io.StringIO()
        )
    assert output.getvalue() == "MESSAGES\nNo messages found.\n"
