"""Focused CLI contracts for fleet session-message operations."""

from __future__ import annotations

import io
import sys

import pytest

from runtime.api.test_constants import TEST_ITEM_REF
from yoke_cli.commands.adapters import session_control_messages as messages
from yoke_cli.commands.registry_session_control import (
    SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY,
    SESSION_CONTROL_SUBCOMMAND_REGISTRY,
)


FULL_MESSAGE_ID = "33333333-3333-4333-8333-333333333333"
FULL_SESSION_ID = "11111111-1111-4111-8111-111111111111"
FULL_MACHINE_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def _top_level_execution(monkeypatch) -> None:
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: False)


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
            "public_refs": [TEST_ITEM_REF],
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


def test_subagent_cannot_send_even_with_parent_session_override(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("act now"))
    dispatched = []
    monkeypatch.setattr(
        messages, "dispatch_and_emit", lambda **kwargs: dispatched.append(kwargs)
    )

    result = messages.say(["--stdin", "--session", "peer", "--session-id", "parent"])

    assert result == 2
    assert dispatched == []
    assert "harness-native parent/subagent channel" in capsys.readouterr().err


def test_subagent_cannot_acknowledge(monkeypatch, capsys) -> None:
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: True)
    dispatched = []
    monkeypatch.setattr(
        messages, "dispatch_and_emit", lambda **kwargs: dispatched.append(kwargs)
    )

    result = messages.session_message_acknowledge(
        ["message-1", "--session-id", "parent"]
    )

    assert result == 2
    assert dispatched == []
    assert "cannot acknowledge Fleet messages" in capsys.readouterr().err


def test_subagent_cannot_cancel(monkeypatch, capsys) -> None:
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: True)
    dispatched = []
    monkeypatch.setattr(
        messages, "dispatch_and_emit", lambda **kwargs: dispatched.append(kwargs)
    )

    result = messages.session_message_cancel(["message-1", "--session-id", "parent"])

    assert result == 2
    assert dispatched == []
    assert "cannot cancel Fleet messages" in capsys.readouterr().err


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
                        "session_id": FULL_SESSION_ID,
                        "project": "yoke",
                        "executor": "codex",
                        "executor_surface": "codex-desktop",
                        "machine_id": FULL_MACHINE_ID,
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
    assert FULL_SESSION_ID in rendered
    assert FULL_MACHINE_ID in rendered
    assert "codex-desktop" in rendered
    assert "yes" in rendered
    assert "|" not in rendered
    assert capsys.readouterr().out == ""


def test_message_list_and_get_use_excerpts_without_full_body_leak() -> None:
    body = "Operator context " + ("private detail " * 10) + "DO-NOT-LEAK"
    message = {
        "message_id": FULL_MESSAGE_ID,
        "sender_actor_id": 7,
        "sender_session_id": "session-sender",
        "body": body,
        "body_sha256": "digest-that-is-not-human-output",
        "created_at": "2026-08-23T12:00:00Z",
        "expires_at": "2026-08-24T12:00:00Z",
        "attempts": [
            {
                "attempt_id": "attempt-1",
                "target_session_id": "session-1",
                "attempt_kind": "wake_relay",
                "result_code": "skipped_surface",
            }
        ],
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
        assert FULL_MESSAGE_ID in rendered
        assert "…" in rendered
        assert body not in rendered
        assert "DO-NOT-LEAK" not in rendered
        assert "body_sha256" not in rendered
        if heading == "MESSAGE":
            assert "DELIVERY ATTEMPTS" in rendered
            assert "skipped surface" in rendered
            assert (
                f"Recipient next step: yoke messages acknowledge {FULL_MESSAGE_ID}"
                in rendered
            )


def test_say_help_teaches_the_complete_top_level_workflow(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        messages.say(["--help"])

    assert exit_info.value.code == 0
    rendered = capsys.readouterr().out
    assert "yoke sessions list --liveness active" in rendered
    assert "yoke say --preview --item PREFIX-N" in rendered
    assert "yoke say --item PREFIX-N --stdin" in rendered
    assert "yoke messages get MESSAGE-ID" in rendered
    assert "yoke messages acknowledge MESSAGE-ID" in rendered
    assert "Top-level sender recovery for an undelivered message" in rendered
    assert "yoke messages cancel MESSAGE-ID" in rendered
    assert "receipts shared with their parent read-only" in rendered
    assert "handle Fleet wake requests" in rendered


def test_sent_message_output_points_to_its_delivery_receipt() -> None:
    response = type(
        "Response",
        (),
        {
            "result": {
                "message_id": FULL_MESSAGE_ID,
                "recipient_count": 0,
                "recipients": [],
            }
        },
    )()
    output = io.StringIO()
    messages.write_message_result(response, output, io.StringIO())
    assert f"Track delivery: yoke messages get {FULL_MESSAGE_ID}" in output.getvalue()


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
