"""A session settles its served model only once the write lands.

Resolving the model reads the harness transcript, so a session stops
resolving as soon as its model is recorded. The regression: it used to
stop as soon as the model was READ. A hook whose relay failed open during
a server rollout carried the model nowhere, the session was already
marked, and ``harness_sessions.model`` stayed NULL for the rest of its
life while the window and the launch ask filled in around it.

Shares the wire fixtures of ``test_yoke_operations_cli_hooks.py`` (the
``local_subset`` holder is autouse there and here via import).
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error

from runtime.api.cli.test_yoke_operations_cli_hooks import (  # noqa: F401
    _FakeResponse,
    cli_main,
)
from yoke_contracts.hook_evaluator_protocol import HOOK_MODEL_CONFIRMATION_FIELD


pytest_plugins = ("runtime.api.cli.test_yoke_operations_cli_hooks",)

SESSION = "s-relay-model"
MODEL = "claude-opus-5"


def _server_response(
    outcome: str = "completed", *, model_confirmation: str | None = None
) -> bytes:
    response = {
        "hook_schema": 1,
        "stdout": "",
        "exit_code": 0,
        "wait_ms": 1,
        "degraded": [],
        "outcome": outcome,
    }
    if model_confirmation is not None:
        response[HOOK_MODEL_CONFIRMATION_FIELD] = model_confirmation
    return json.dumps(response).encode("utf-8")


def _claude_session(monkeypatch, tmp_path) -> None:
    """One claude session whose transcript already names its served model."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"type": "assistant", "message": {"model": MODEL}}) + "\n"
    )
    monkeypatch.setattr("yoke_cli.config.machine_config.yoke_home", lambda: tmp_path)
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.detect_executor", lambda: "claude-code"
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "tool_name": "Bash",
                    "session_id": SESSION,
                    "transcript_path": str(transcript),
                }
            )
        ),
    )


def _posted_models(bodies: list[dict]) -> list[object]:
    return [body.get("model") for body in bodies]


def test_a_lost_relay_leaves_the_model_to_ride_the_next_hook(
    monkeypatch,
    capsys,
    tmp_path,
    https_connection,
    local_subset,
) -> None:
    posted: list[dict] = []

    def unreachable(request, timeout=None):
        posted.append(json.loads(request.data.decode("utf-8")))
        raise urllib.error.URLError("connection refused")

    _claude_session(monkeypatch, tmp_path)
    monkeypatch.setattr("urllib.request.urlopen", unreachable)
    assert cli_main(["hook", "evaluate", "PreToolUse"]) == 0
    assert "degraded to no-op allow" in capsys.readouterr().err

    _claude_session(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: (
            posted.append(json.loads(request.data.decode("utf-8")))
            or _FakeResponse(_server_response(model_confirmation=MODEL))
        ),
    )
    assert cli_main(["hook", "evaluate", "PostToolUse"]) == 0

    assert _posted_models(posted) == [MODEL, MODEL]
    assert (tmp_path / "relay-model-shipped" / SESSION).exists()


def test_a_timed_out_relay_does_not_settle_the_session(
    monkeypatch,
    capsys,
    tmp_path,
    https_connection,
    local_subset,
) -> None:
    """A timeout may have skipped the server's registration tail.

    The response is the hook contract and the tool call proceeds, but
    nothing here proves the row was written, so the facts stay unsettled.
    """
    _claude_session(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(_server_response(outcome="timeout")),
    )

    assert cli_main(["hook", "evaluate", "PreToolUse"]) == 0

    assert not (tmp_path / "relay-model-shipped" / SESSION).exists()


def test_a_completed_response_without_a_model_receipt_does_not_settle(
    monkeypatch,
    tmp_path,
    https_connection,
    local_subset,
) -> None:
    """A resident's synthetic allow is not a durable control-plane reply."""
    _claude_session(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(_server_response()),
    )

    assert cli_main(["hook", "evaluate", "PreToolUse"]) == 0
    assert not (tmp_path / "relay-model-shipped" / SESSION).exists()


def test_a_landed_relay_settles_and_stops_reading_the_transcript(
    monkeypatch,
    capsys,
    tmp_path,
    https_connection,
    local_subset,
) -> None:
    posted: list[dict] = []

    def accept(request, timeout=None):
        posted.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse(_server_response(model_confirmation=MODEL))

    _claude_session(monkeypatch, tmp_path)
    monkeypatch.setattr("urllib.request.urlopen", accept)
    assert cli_main(["hook", "evaluate", "PreToolUse"]) == 0
    assert (tmp_path / "relay-model-shipped" / SESSION).exists()

    _claude_session(monkeypatch, tmp_path)
    monkeypatch.setattr("urllib.request.urlopen", accept)
    assert cli_main(["hook", "evaluate", "PostToolUse"]) == 0

    assert _posted_models(posted) == [MODEL, None]
