"""Client identity evidence carried by the HTTPS hook relay."""

from __future__ import annotations

import io
import json
import sys

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.transport.https import HttpsConnection


_RESOLVE = "yoke_cli.transport.https.resolve_https_connection"


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


@pytest.fixture(autouse=True)
def local_subset(monkeypatch) -> None:
    from yoke_harness.hooks.local_subset import LocalSubsetEvaluation

    monkeypatch.setattr(
        "yoke_harness.hooks.relay.evaluate_local_subset",
        lambda *_a, **_k: LocalSubsetEvaluation(stdout="", exit_code=0, denied=False),
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay._client_lint_config_snapshot",
        lambda _payload: {},
    )


@pytest.fixture()
def https_connection(monkeypatch) -> HttpsConnection:
    connection = HttpsConnection(api_url="https://env.example", token="tok")
    monkeypatch.setattr(_RESOLVE, lambda: connection)
    return connection


def _completed_response() -> _FakeResponse:
    return _FakeResponse(
        json.dumps(
            {
                "hook_schema": 1,
                "stdout": "",
                "exit_code": 0,
                "wait_ms": 1,
                "degraded": [],
                "outcome": "completed",
            }
        ).encode("utf-8")
    )


def test_hook_evaluate_https_registration_events_carry_client_model(
    monkeypatch,
    https_connection,
) -> None:
    raw_stdin = json.dumps(
        {
            "session_id": "s-model",
            "transcript_path": "/t/live.jsonl",
            "prompt": "hi",
        }
    )
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
        return _completed_response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert cli_main(["hook", "evaluate", "UserPromptSubmit"]) == 0
    assert captured["body"]["model"] == "claude-fable-5[1m]"
    assert captured["body"]["entrypoint"] == "claude-desktop"


def test_hook_evaluate_https_placeholder_client_model_not_sent(
    monkeypatch,
    https_connection,
) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
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
        return _completed_response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert cli_main(["hook", "evaluate", "SessionStart"]) == 0
    assert captured["body"]["model"] is None
