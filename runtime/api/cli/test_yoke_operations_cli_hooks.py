"""Tests for ``yoke hook evaluate`` (local delegation + https relay).

Verdict-composition coverage (client deny short-circuit, allow-stdout
merge, degradation preserving the client half) lives in
``test_yoke_hooks_relay_compose.py`` (350-line cap).
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.transport.https import HttpsConnection, TransportError


_RESOLVE = "yoke_cli.transport.https.resolve_https_connection"


@pytest.fixture(autouse=True)
def local_subset(monkeypatch):
    """Pin the relay's client-side half to a deterministic allow.

    The relay always evaluates the LOCAL_STATE_POLICIES subset before
    posting; wire-contract tests must not run the real registry chain on
    the test machine. Composition tests reassign ``holder.result``.
    """
    from yoke_harness.hooks.local_subset import LocalSubsetEvaluation

    holder = SimpleNamespace(
        result=LocalSubsetEvaluation(stdout="", exit_code=0, denied=False),
        calls=[],
    )

    def fake(
        event_name,
        stdin_data,
        executor,
        agent_type,
        deadline,
        *,
        defer_main_commit=False,
        lint_config_snapshot=None,
    ):
        holder.calls.append((
            event_name, executor, agent_type, defer_main_commit,
            lint_config_snapshot,
        ))
        return holder.result

    monkeypatch.setattr(
        "yoke_harness.hooks.relay.evaluate_local_subset", fake,
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay._client_lint_config_snapshot",
        lambda _payload: {},
    )
    return holder


def test_hook_evaluate_delegates_to_hook_runner(monkeypatch) -> None:
    monkeypatch.setattr(_RESOLVE, lambda: None)
    with patch(
        "yoke_harness.hooks.relay.evaluate_hook_event",
        return_value=0,
    ) as hook_main:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli_main(["hook", "evaluate", "PreToolUse"])

    assert rc == 0
    hook_main.assert_called_once_with("PreToolUse", dry_run=False)


def test_hook_evaluate_dry_run_delegates_flag_and_skips_transport(
    monkeypatch,
) -> None:
    def _boom() -> None:
        raise AssertionError("--dry-run must never resolve transport")

    monkeypatch.setattr(_RESOLVE, _boom)
    with patch(
        "yoke_harness.hooks.relay.evaluate_hook_event",
        return_value=0,
    ) as hook_main:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli_main(["hook", "evaluate", "Stop", "--dry-run"])

    assert rc == 0
    hook_main.assert_called_once_with("Stop", dry_run=True)


def test_hook_evaluate_missing_event_returns_two() -> None:
    with patch("yoke_harness.hooks.relay.evaluate_hook_event") as hook_main:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli_main(["hook", "evaluate"])

    assert rc == 2
    hook_main.assert_not_called()


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def geturl(self) -> str:
        return "https://env.example/v1/hooks/evaluate"

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args) -> bool:
        return False


@pytest.fixture()
def https_connection(monkeypatch):
    connection = HttpsConnection(api_url="https://env.example", token="tok")
    monkeypatch.setattr(_RESOLVE, lambda: connection)
    return connection


def test_hook_evaluate_https_posts_contract_and_relays(
    monkeypatch, capsys, https_connection,
) -> None:
    raw_stdin = '{"tool_name": "Bash", "tool_input": {"command": "ls"}}'
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw_stdin))
    monkeypatch.setenv("YOKE_HOOK_AGENT_TYPE", "engineer")
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.detect_executor",
        lambda: "claude-code",
    )
    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse(json.dumps({
            "hook_schema": 1,
            "stdout": "DENY: blocked by policy",
            "exit_code": 2,
            "wait_ms": 41,
            "degraded": [],
            "outcome": "denied",
        }).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    rc = cli_main(["hook", "evaluate", "PreToolUse"])

    request = captured["request"]
    assert request.full_url == "https://env.example/v1/hooks/evaluate"
    assert request.get_header("Authorization") == "Bearer tok"
    body = json.loads(request.data.decode("utf-8"))
    assert body["hook_schema"] == 1
    assert body["event_name"] == "PreToolUse"
    assert body["stdin"] == raw_stdin
    assert body["executor"] == "claude-code"
    assert body["agent_type"] == "engineer"
    assert body["payload_extra"] == {}
    assert "entrypoint" in body
    assert body["model"] is None, "tool-call relays never pay the transcript read"
    assert 0 < body["deadline_ms"] <= 3000
    assert 0 < captured["timeout"] <= 3.0
    out = capsys.readouterr()
    assert out.out == "DENY: blocked by policy"
    assert rc == 2


def test_hook_evaluate_https_writes_client_anchor_before_relay(
    monkeypatch, https_connection,
) -> None:
    # Relayed hooks never run the local runner, so the relay itself must
    # bind the payload session to THIS machine's process ancestry — the
    # server cannot (the caller's process tree is not the server's).
    raw_stdin = json.dumps({
        "tool_name": "Bash",
        "session_id": "s-relay-anchor",
        "transcript_path": "/t/relay.jsonl",
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw_stdin))
    recorded: list[tuple] = []
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor",
        lambda sid, transcript_path="", **_k: recorded.append(
            (sid, transcript_path)
        ),
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(json.dumps({
            "hook_schema": 1, "stdout": "", "exit_code": 0,
            "wait_ms": 1, "degraded": [], "outcome": "completed",
        }).encode("utf-8")),
    )
    rc = cli_main(["hook", "evaluate", "PreToolUse"])
    assert rc == 0
    assert recorded == [("s-relay-anchor", "/t/relay.jsonl")]


def test_hook_evaluate_https_anchor_failure_never_breaks_relay(
    monkeypatch, https_connection,
) -> None:
    monkeypatch.setattr(
        sys, "stdin",
        io.StringIO('{"tool_name": "Bash", "session_id": "s-x"}'),
    )

    def _boom(*_a, **_k):
        raise RuntimeError("anchor write exploded")

    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor",
        _boom,
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(json.dumps({
            "hook_schema": 1, "stdout": "ok", "exit_code": 0,
            "wait_ms": 1, "degraded": [], "outcome": "completed",
        }).encode("utf-8")),
    )
    assert cli_main(["hook", "evaluate", "PreToolUse"]) == 0


def test_hook_evaluate_https_sessionless_payload_writes_no_anchor(
    monkeypatch, https_connection,
) -> None:
    monkeypatch.setattr(
        sys, "stdin", io.StringIO('{"tool_name": "Bash"}'),
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor",
        lambda *_a, **_k: pytest.fail("sessionless payload must not anchor"),
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(json.dumps({
            "hook_schema": 1, "stdout": "", "exit_code": 0,
            "wait_ms": 1, "degraded": [], "outcome": "completed",
        }).encode("utf-8")),
    )
    assert cli_main(["hook", "evaluate", "PreToolUse"]) == 0


def test_hook_evaluate_half_configured_https_degrades_to_noop(
    monkeypatch, capsys,
) -> None:
    def _raise() -> None:
        raise TransportError("env 'prod' declares https transport but no api_url")

    monkeypatch.setattr(_RESOLVE, _raise)
    with patch("yoke_harness.hooks.relay.evaluate_hook_event") as hook_main:
        rc = cli_main(["hook", "evaluate", "SessionStart"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out == ""
    assert "degraded to no-op allow" in out.err
    hook_main.assert_not_called()


def test_hook_evaluate_https_registration_events_carry_client_model(
    monkeypatch, https_connection,
) -> None:
    # Model parity over the relay depends on client-side transcript
    # detection (the server can never read the client transcript); the
    # cost is paid only on registration-class events.
    raw_stdin = json.dumps({
        "session_id": "s-model",
        "transcript_path": "/t/live.jsonl",
        "prompt": "hi",
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw_stdin))
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.detect_executor",
        lambda: "claude-code",
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_relay.detect_model",
        lambda executor, transcript_path="": "claude-fable-5[1m]",
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_relay.detect_entrypoint",
        lambda: "claude-desktop",
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor",
        lambda *_a, **_k: None,
    )
    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps({
            "hook_schema": 1, "stdout": "", "exit_code": 0,
            "wait_ms": 1, "degraded": [], "outcome": "completed",
        }).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert cli_main(["hook", "evaluate", "UserPromptSubmit"]) == 0
    assert captured["body"]["model"] == "claude-fable-5[1m]"
    assert captured["body"]["entrypoint"] == "claude-desktop"


def test_hook_evaluate_https_placeholder_client_model_not_sent(
    monkeypatch, https_connection,
) -> None:
    monkeypatch.setattr(
        sys, "stdin",
        io.StringIO('{"session_id": "s-m2", "transcript_path": "/t/x.jsonl"}'),
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.detect_executor",
        lambda: "claude-code",
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_relay.detect_model",
        lambda executor, transcript_path="": "unknown",
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor",
        lambda *_a, **_k: None,
    )
    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps({
            "hook_schema": 1, "stdout": "", "exit_code": 0,
            "wait_ms": 1, "degraded": [], "outcome": "completed",
        }).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert cli_main(["hook", "evaluate", "SessionStart"]) == 0
    assert captured["body"]["model"] is None
