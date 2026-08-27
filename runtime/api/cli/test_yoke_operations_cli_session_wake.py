"""CLI contracts for an operator-forced native session wake."""

from __future__ import annotations

import io
from types import SimpleNamespace

from yoke_cli.commands.adapters import session_control_wake as wake
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

    assert wake.session_wake(["--item", "YOK-7", "--prompt", "Continue."]) == 0

    assert calls[0]["payload"] == {"item_ref": "YOK-7", "prompt": "Continue."}
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
        "codex-cli",
        "yoke messages get message-1",
    ):
        assert expected in rendered
