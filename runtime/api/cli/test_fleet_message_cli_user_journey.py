"""Operator journeys through the registered Fleet messaging CLI surface."""

from __future__ import annotations

import copy
import io
import os
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters import session_control_messages as messages
from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)


SENDER_ID = "11111111-1111-4111-8111-111111111111"
RECIPIENT_ID = "22222222-2222-4222-8222-222222222222"
MESSAGE_ID = "33333333-3333-4333-8333-333333333333"
MACHINE_ID = "44444444-4444-4444-8444-444444444444"
PRIVATE_SUFFIX = "DO-NOT-LEAK-IN-COMMAND-EVIDENCE"
MESSAGE_BODY = "private operator context " + ("detail " * 14) + PRIVATE_SUFFIX


def _success(request: FunctionCallRequest, result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result=result,
    )


def _failure(
    request: FunctionCallRequest, code: str, message: str
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(code=code, message=message),
    )


class _FleetBroker:
    """Stateful engine-boundary fake behind the real CLI dispatch path."""

    def __init__(self, recipient_mode: str = "messageable") -> None:
        self.recipient_mode = recipient_mode
        self.requests: list[FunctionCallRequest] = []
        self.argv: list[tuple[str, ...]] = []
        self.message: dict | None = None

    def __call__(self, request: FunctionCallRequest) -> FunctionCallResponse:
        self.requests.append(request)
        handler = getattr(self, "_" + request.function.replace(".", "_"))
        return handler(request)

    def _recipient(self) -> dict:
        messageable = self.recipient_mode == "messageable"
        return {
            "session_id": RECIPIENT_ID,
            "project": "yoke",
            "executor": "codex",
            "executor_surface": "codex-desktop",
            "machine_id": MACHINE_ID,
            "liveness": "active",
            "messageability": {
                "messageable": messageable,
                "reason": None if messageable else "hook_route_missing",
            },
        }

    def _sessions_list(self, request: FunctionCallRequest) -> FunctionCallResponse:
        return _success(
            request,
            {
                "fields": ["project"],
                "rows": [
                    {
                        **self._recipient(),
                        "focus": "Fleet verification",
                        "role": "implementation",
                        "relay": "ready",
                    }
                ],
            },
        )

    def _session_control_message_preview(
        self, request: FunctionCallRequest
    ) -> FunctionCallResponse:
        if self.recipient_mode == "empty":
            return _failure(request, "zero_recipients", "selector found no sessions")
        return _success(
            request,
            {"recipient_count": 1, "recipients": [self._recipient()]},
        )

    def _session_control_message_send(
        self, request: FunctionCallRequest
    ) -> FunctionCallResponse:
        if self.recipient_mode != "messageable":
            return _failure(
                request,
                "unroutable_recipient",
                "recipient has no version-qualified hook route",
            )
        recipient = {
            "session_id": RECIPIENT_ID,
            "project_id": 1,
            "state": "injected",
            "executor_surface": "codex-desktop",
            "machine_id": MACHINE_ID,
            "routing_snapshot": self._recipient(),
        }
        self.message = {
            "message_id": MESSAGE_ID,
            "sender_session_id": request.actor.session_id,
            "body": request.payload["body"],
            "created_at": "2026-08-23T12:00:00Z",
            "expires_at": "2026-08-24T12:00:00Z",
            "recipients": [recipient],
        }
        return _success(
            request,
            {
                "message_id": MESSAGE_ID,
                "recipient_count": 1,
                "recipients": [self._recipient()],
                "deduplicated": False,
            },
        )

    def _session_control_message_list(
        self, request: FunctionCallRequest
    ) -> FunctionCallResponse:
        found = [copy.deepcopy(self.message)] if self.message else []
        return _success(request, {"messages": found, "count": len(found)})

    def _session_control_message_get(
        self, request: FunctionCallRequest
    ) -> FunctionCallResponse:
        return _success(request, {"message": copy.deepcopy(self.message)})

    def _session_control_message_acknowledge(
        self, request: FunctionCallRequest
    ) -> FunctionCallResponse:
        if request.actor.session_id != RECIPIENT_ID:
            return _failure(
                request,
                "recipient_session_required",
                "only an addressed recipient session can acknowledge this message",
            )
        assert self.message is not None
        self.message["recipients"][0]["state"] = "acknowledged"
        return _success(request, {"message": copy.deepcopy(self.message)})


@pytest.fixture(autouse=True)
def _top_level_execution(monkeypatch) -> None:
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: False)


def _run_cli(
    broker: _FleetBroker,
    argv: list[str],
    *,
    session_id: str,
    stdin: str = "",
) -> tuple[int, str, str]:
    broker.argv.append(tuple(argv))
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch.dict(os.environ, {"YOKE_SESSION_ID": session_id}, clear=False),
        patch("sys.stdin", io.StringIO(stdin)),
        patch(
            "yoke_cli.transport.dispatcher.https_transport.resolve_https_connection",
            return_value=None,
        ),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=broker,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        result = cli_main(argv)
    return result, stdout.getvalue(), stderr.getvalue()


def test_operator_journey_discovers_sends_reads_and_acknowledges() -> None:
    broker = _FleetBroker()
    evidence: list[str] = []

    result, output, error = _run_cli(
        broker,
        ["sessions", "list", "--liveness", "active"],
        session_id=SENDER_ID,
    )
    assert result == 0 and error == ""
    assert RECIPIENT_ID in output
    assert "yes" in output
    evidence.append(output)

    result, output, error = _run_cli(
        broker,
        ["say", "--preview", "--session", RECIPIENT_ID],
        session_id=SENDER_ID,
    )
    assert result == 0 and error == ""
    assert "MESSAGE PREVIEW" in output
    assert RECIPIENT_ID in output
    evidence.append(output)

    result, output, error = _run_cli(
        broker,
        ["say", "--stdin", "--session", RECIPIENT_ID],
        session_id=SENDER_ID,
        stdin=MESSAGE_BODY,
    )
    assert result == 0 and error == ""
    assert MESSAGE_ID in output
    assert f"yoke messages get {MESSAGE_ID}" in output
    evidence.append(output)

    for argv in (
        ["messages", "list", "--recipient-session", RECIPIENT_ID],
        ["messages", "get", MESSAGE_ID],
    ):
        result, output, error = _run_cli(
            broker,
            argv,
            session_id=RECIPIENT_ID,
        )
        assert result == 0 and error == ""
        assert MESSAGE_ID in output
        evidence.append(output)

    result, _output, error = _run_cli(
        broker,
        ["messages", "acknowledge", MESSAGE_ID],
        session_id=SENDER_ID,
    )
    assert result == 1
    assert "recipient_session_required" in error
    evidence.append(error)

    result, output, error = _run_cli(
        broker,
        ["messages", "acknowledge", MESSAGE_ID],
        session_id=RECIPIENT_ID,
    )
    assert result == 0 and error == ""
    assert "acknowledged" in output
    evidence.append(output)

    assert [request.function for request in broker.requests] == [
        "sessions.list",
        "session_control.message.preview",
        "session_control.message.send",
        "session_control.message.list",
        "session_control.message.get",
        "session_control.message.acknowledge",
        "session_control.message.acknowledge",
    ]
    send = broker.requests[2]
    assert send.actor.session_id == SENDER_ID
    assert send.payload == {
        "selector": {"session_ids": [RECIPIENT_ID]},
        "body": MESSAGE_BODY,
    }
    assert broker.requests[3].actor.session_id == RECIPIENT_ID
    assert broker.requests[3].payload["session_id"] == RECIPIENT_ID
    assert MESSAGE_BODY not in " ".join(token for argv in broker.argv for token in argv)
    rendered_evidence = "\n".join(evidence)
    assert MESSAGE_BODY not in rendered_evidence
    assert PRIVATE_SUFFIX not in rendered_evidence


def test_subagent_send_and_ack_stop_before_engine_dispatch(monkeypatch) -> None:
    broker = _FleetBroker()
    monkeypatch.setattr(messages, "is_subagent_execution", lambda: True)

    send_result, _output, send_error = _run_cli(
        broker,
        ["say", "--stdin", "--session", RECIPIENT_ID],
        session_id=SENDER_ID,
        stdin=MESSAGE_BODY,
    )
    ack_result, _output, ack_error = _run_cli(
        broker,
        ["messages", "acknowledge", MESSAGE_ID],
        session_id=SENDER_ID,
    )

    assert send_result == ack_result == 2
    assert broker.requests == []
    assert "harness-native parent/subagent channel" in send_error
    assert "receipts shared with their parent read-only" in send_error
    assert "cannot acknowledge Fleet messages" in ack_error


def test_preview_explains_when_an_exact_recipient_is_missing() -> None:
    broker = _FleetBroker("empty")

    result, output, error = _run_cli(
        broker,
        ["say", "--preview", "--session", RECIPIENT_ID],
        session_id=SENDER_ID,
    )

    assert result == 1
    assert output == ""
    assert "zero_recipients" in error
    assert broker.message is None


def test_unroutable_recipient_is_visible_before_send_and_send_refuses() -> None:
    broker = _FleetBroker("unroutable")

    preview_result, preview_output, preview_error = _run_cli(
        broker,
        ["say", "--preview", "--session", RECIPIENT_ID],
        session_id=SENDER_ID,
    )
    send_result, send_output, send_error = _run_cli(
        broker,
        ["say", "--stdin", "--session", RECIPIENT_ID],
        session_id=SENDER_ID,
        stdin=MESSAGE_BODY,
    )

    assert preview_result == 0 and preview_error == ""
    assert "no (hook route mi…" in preview_output
    assert send_result == 1 and send_output == ""
    assert "unroutable_recipient" in send_error
    assert MESSAGE_BODY not in send_error
    assert PRIVATE_SUFFIX not in send_error
    assert broker.message is None
