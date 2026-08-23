"""Focused CLI contracts for fleet session-message operations."""

from __future__ import annotations

import io
import sys

from runtime.api.test_constants import TEST_ITEM_REF
from yoke_cli.commands.adapters import session_control_messages as messages
from yoke_cli.commands.registry_session_control import (
    SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY,
    SESSION_CONTROL_SUBCOMMAND_REGISTRY,
)


def test_say_preview_dispatches_semantic_selector(monkeypatch) -> None:
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(messages, "dispatch_and_emit", _dispatch)
    assert (
        messages.say(
            [
                "--preview",
                "--item",
                TEST_ITEM_REF,
                "--project",
                "platform",
                "--surface",
                "codex-desktop",
                "--liveness",
                "active",
                "--exclude-session",
                "session-old",
            ]
        )
        == 0
    )

    assert captured["function_id"] == "session_control.message.preview"
    assert captured["target"].kind == "global"
    assert captured["payload"] == {
        "selector": {
            "item_refs": [TEST_ITEM_REF],
            "projects": ["platform"],
            "executor_surfaces": ["codex-desktop"],
            "liveness": ["active"],
            "exclude_session_ids": ["session-old"],
        }
    }


def test_say_send_reads_body_only_from_stdin(monkeypatch) -> None:
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(messages, "dispatch_and_emit", _dispatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("act now"))
    assert (
        messages.say(
            [
                "--stdin",
                "--session",
                "session-1",
                "--idempotency-key",
                "send-1",
            ]
        )
        == 0
    )

    assert captured["function_id"] == "session_control.message.send"
    assert captured["payload"] == {
        "selector": {"session_ids": ["session-1"]},
        "body": "act now",
        "idempotency_key": "send-1",
    }
    assert captured["sensitive_values"] == ("act now",)


def test_say_refuses_a_message_body_in_process_arguments(capsys) -> None:
    assert messages.say(["body-in-argv", "--stdin", "--session", "session-1"]) == 2
    assert "unrecognized arguments: body-in-argv" in capsys.readouterr().err


def test_message_list_get_acknowledge_and_cancel_payloads(monkeypatch) -> None:
    calls = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(messages, "dispatch_and_emit", _dispatch)
    assert (
        messages.session_message_list(
            [
                "--state",
                "injected",
                "--recipient-session",
                "session-2",
                "--limit",
                "8",
            ]
        )
        == 0
    )
    assert messages.session_message_get(["message-1"]) == 0
    assert messages.session_message_acknowledge(["message-1"]) == 0
    assert messages.session_message_cancel(["message-1"]) == 0

    assert [call["function_id"] for call in calls] == [
        "session_control.message.list",
        "session_control.message.get",
        "session_control.message.acknowledge",
        "session_control.message.cancel",
    ]
    assert calls[0]["payload"] == {
        "state": "injected",
        "session_id": "session-2",
        "limit": 8,
    }
    assert all(call["payload"] == {"message_id": "message-1"} for call in calls[1:])


def test_message_human_output_keeps_recipient_evidence(capsys) -> None:
    response = type(
        "Response",
        (),
        {
            "result": {
                "recipient_count": 1,
                "confirmation_token": "confirm-1",
                "recipients": [
                    {
                        "session_id": "session-1",
                        "project": "yoke",
                        "executor": "codex",
                        "executor_surface": "codex-desktop",
                        "machine_id": "machine-1",
                        "liveness": "active",
                        "messageability": {"messageable": True},
                    }
                ],
            }
        },
    )()
    output = io.StringIO()
    messages.write_message_result(response, output, io.StringIO())
    rendered = output.getvalue()
    lines = rendered.splitlines()
    assert lines[0] == "MESSAGE PREVIEW"
    assert "Recipients" in rendered
    assert "Confirmation token" in rendered
    assert "RECIPIENTS" in rendered
    assert "SESSION" in rendered
    assert "MESSAGEABLE" in rendered
    assert "session-1" in rendered
    assert "codex-desktop" in rendered
    assert "yes" in rendered
    assert "|" not in rendered
    assert capsys.readouterr().out == ""


def test_message_list_and_get_use_excerpts_without_full_body_leak() -> None:
    body = "Operator context " + ("private detail " * 10) + "DO-NOT-LEAK"
    message = {
        "message_id": "message-1",
        "sender_actor_id": 7,
        "sender_session_id": "session-sender",
        "body": body,
        "body_sha256": "digest-that-is-not-human-output",
        "created_at": "2026-08-23T12:00:00Z",
        "expires_at": "2026-08-24T12:00:00Z",
        "recipients": [
            {
                "session_id": "session-1",
                "project_id": 1,
                "state": "injected",
                "executor_surface": "codex-desktop",
                "machine_id": "machine-1",
                "routing_snapshot": {
                    "project": "yoke",
                    "messageability": {"messageable": True},
                },
            }
        ],
    }

    for result, heading in (
        ({"messages": [message], "count": 1}, "MESSAGES"),
        ({"message": message}, "MESSAGE"),
    ):
        output = io.StringIO()
        response = type("Response", (), {"result": result})()
        messages.write_message_result(response, output, io.StringIO())
        rendered = output.getvalue()
        assert rendered.splitlines()[0] == heading
        assert "BODY" in rendered.upper()
        assert "CREATED (UTC)" in rendered.upper()
        assert "…" in rendered
        assert body not in rendered
        assert "DO-NOT-LEAK" not in rendered
        assert "body_sha256" not in rendered


def test_message_list_has_an_explicit_empty_state() -> None:
    response = type("Response", (), {"result": {"messages": [], "count": 0}})()
    output = io.StringIO()
    messages.write_message_result(response, output, io.StringIO())
    assert output.getvalue() == "MESSAGES\nNo messages found.\n"


def test_registry_exposes_canonical_functions_and_concise_aliases() -> None:
    expected = {
        "session_control.message.preview",
        "session_control.message.send",
        "session_control.message.list",
        "session_control.message.get",
        "session_control.message.acknowledge",
        "session_control.message.cancel",
    }
    registered = {
        function_id
        for function_id, _adapter in SESSION_CONTROL_SUBCOMMAND_REGISTRY.values()
    }
    assert expected <= registered
    assert SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY[("say",)][0] == (
        "session_control.message.send"
    )
    assert (
        SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY[("messages", "acknowledge")][0]
        == "session_control.message.acknowledge"
    )
