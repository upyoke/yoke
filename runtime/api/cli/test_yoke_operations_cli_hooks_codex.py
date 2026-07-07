"""Codex leg of the hook-relay client identity contract.

Split from ``test_yoke_operations_cli_hooks.py`` (350-line cap): the
client-side cache-write relocation and the no-fabricated-model rule.
"""

from __future__ import annotations

import io
import json
import sys

from runtime.api.cli.test_yoke_operations_cli_hooks import (  # noqa: F401
    _FakeResponse,
    cli_main,
    https_connection,
    local_subset,
)


def test_hook_evaluate_https_codex_session_start_captures_and_resolves(
    monkeypatch, https_connection,
) -> None:
    """Codex half of the client-side relocation: the relay writes the
    runtime cache (the remote-skipped session-dispatch write) and ships
    payload-thread-resolved model + entrypoint — never env-dependent."""
    raw_stdin = json.dumps({
        "session_id": "codex-thread-1",
        "transcript_path": "/t/codex.jsonl",
        "model": "gpt-6-real",
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw_stdin))
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.detect_executor", lambda: "codex",
    )
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    cache_writes: list[tuple] = []
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.write_runtime_cache",
        lambda sid, payload: cache_writes.append((sid, payload)),
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_relay._codex_resolve_model",
        lambda thread_id=None: "gpt-6-real" if thread_id == "codex-thread-1" else None,
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_relay._codex_resolve_entrypoint",
        lambda thread_id=None: "codex-desktop" if thread_id == "codex-thread-1" else None,
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
    assert cache_writes == [("codex-thread-1", raw_stdin)]
    assert captured["body"]["model"] == "gpt-6-real"
    assert captured["body"]["entrypoint"] == "codex-desktop"


def test_hook_evaluate_https_codex_unresolved_model_ships_nothing(
    monkeypatch, https_connection,
) -> None:
    # Resolver finds nothing -> wire carries None; a fabricated default
    # must never reach the row (field regression: literal "gpt-5.4").
    monkeypatch.setattr(
        sys, "stdin", io.StringIO('{"session_id": "codex-thread-2"}'),
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.detect_executor", lambda: "codex",
    )
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_relay._codex_resolve_model",
        lambda thread_id=None: None,
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_relay._codex_resolve_entrypoint",
        lambda thread_id=None: None,
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.write_runtime_cache",
        lambda *_a: None,
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
    assert captured["body"]["model"] is None
    assert captured["body"]["entrypoint"] is None
