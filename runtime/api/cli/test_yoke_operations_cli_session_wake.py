"""CLI contracts for an explicit native session wake."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from yoke_cli.commands import _helpers
from yoke_cli.commands.adapters import session_control_wake as wake
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_cli.commands.registry_session_control import (
    SESSION_CONTROL_SUBCOMMAND_REGISTRY,
)


def test_session_wake_dispatches_an_exact_session(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        wake,
        "dispatch_and_emit",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    assert wake.session_wake(["worker-session", "--session-id", "steerer"]) == 0

    assert calls[0]["function_id"] == "session_control.session.wake"
    assert calls[0]["target"].kind == "global"
    assert calls[0]["session_id"] == "steerer"
    assert calls[0]["payload"] == {"session_id": "worker-session"}


def test_session_wake_resolves_an_item_holder_and_carries_a_prompt(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        wake,
        "dispatch_and_emit",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    assert (
        wake.session_wake(
            [
                "--item",
                "YOK-7",
                "--prompt",
                "Continue.",
                "--idempotency-key",
                "watchdog:YOK-7",
            ]
        )
        == 0
    )

    assert calls[0]["payload"] == {
        "public_ref": "YOK-7",
        "prompt": "Continue.",
        "idempotency_key": "watchdog:YOK-7",
    }
    assert calls[0]["sensitive_values"] == ("Continue.",)


def test_session_wake_requires_exactly_one_target(capsys) -> None:
    assert wake.session_wake([]) == 2
    assert wake.session_wake(["session-1", "--item", "YOK-7"]) == 2
    assert "exactly one" in capsys.readouterr().err


def test_canonical_route_uses_the_registered_wake_function() -> None:
    assert SESSION_CONTROL_SUBCOMMAND_REGISTRY[
        ("session-control", "session", "wake")
    ] == ("session_control.session.wake", wake.session_wake)


def test_human_output_prints_attempt_result_evidence_and_recovery() -> None:
    stdout = io.StringIO()
    wake._write_wake_result(
        SimpleNamespace(
            result={
                "target_session_id": "worker-session",
                "target_liveness": "active",
                "message_id": "message-1",
                "result_code": "accepted",
                "deduplicated": True,
                "wake_attempt_count": 1,
                "last_wake_at": "2026-08-27T15:00:00Z",
                "attempt": {"attempt_id": "attempt-1"},
                "evidence": {"surface": "codex-cli"},
                "recovery": "yoke messages get message-1",
            }
        ),
        stdout,
        io.StringIO(),
    )

    rendered = stdout.getvalue()
    for expected in (
        "SESSION WAKE",
        "worker-session",
        "attempt-1",
        "accepted",
        "DEDUPLICATED",
        "WAKE COUNT",
        "2026-08-27T15:00:00Z",
        "codex-cli",
        "yoke messages get message-1",
    ):
        assert expected in rendered


@pytest.mark.parametrize("json_mode", [False, True])
def test_refused_wake_prints_its_named_reason_and_recovery(
    monkeypatch, capsys, json_mode
) -> None:
    message = (
        "Native wake refused: wake_queued for message pending-wake. "
        "Inspect `yoke messages get pending-wake` and retry after the current "
        "attempt settles."
    )
    response = FunctionCallResponse(
        success=False,
        function="session_control.session.wake",
        version="v1",
        request_id="refused-wake",
        result={},
        error=FunctionError(code="wake_in_flight", message=message),
    )
    monkeypatch.setattr(_helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(_helpers, "call_dispatcher", lambda **_: response)

    arguments = ["worker-session", "--session-id", "steerer"]
    assert wake.session_wake(arguments + (["--json"] if json_mode else [])) == 1

    captured = capsys.readouterr()
    if json_mode:
        envelope = json.loads(captured.out)
        assert envelope["success"] is False
        assert envelope["error"]["code"] == "wake_in_flight"
        assert envelope["error"]["message"] == message
    else:
        assert "error (wake_in_flight):" in captured.err
        assert message in captured.err
