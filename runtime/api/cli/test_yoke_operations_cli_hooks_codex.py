"""Codex leg of the hook-relay client identity contract.

Split from ``test_yoke_operations_cli_hooks.py`` (350-line cap): the
client-side cache-write relocation and the no-fabricated-model rule.
"""

from __future__ import annotations

from yoke_contracts.session_model_facts import SessionModelFacts
import io
import json
import sys

import pytest

from yoke_core.domain.session_ambient_identity import AMBIENT_ENV_VARS
from yoke_harness.hooks import relay

from runtime.api.cli.test_yoke_operations_cli_hooks import _FakeResponse, cli_main


# ``local_subset`` and ``https_connection`` are fixtures, not values: loading
# the sibling as a plugin registers them for these tests without importing
# names that every use as a test parameter then shadows.
pytest_plugins = ("runtime.api.cli.test_yoke_operations_cli_hooks",)


@pytest.fixture(autouse=True)
def detached_from_runner_session(monkeypatch):
    """Detach these relay tests from the session the runner itself runs under.

    The relay resolves identity from the whole ambient env chain, so naming
    a couple of variables by hand leaves the rest of ``AMBIENT_ENV_VARS``
    free to answer with the runner's own live session id: green on CI,
    which has no session, and red on every developer machine, which has
    one. Clearing the contract's chain rather than a hand-written subset
    keeps the isolation correct as that chain grows. Dropping the anchor
    write keeps a synthetic payload out of the machine's real
    process-anchor registry, the next channel that same chain consults.
    """
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(relay, "_record_client_anchor", lambda *_a, **_k: None)


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
    cache_writes: list[tuple] = []
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.write_runtime_cache",
        lambda sid, payload: cache_writes.append((sid, payload)),
    )
    monkeypatch.setattr(
        "yoke_harness.model_attestation._codex_facts",
        lambda payload: SessionModelFacts(
            model="gpt-6-real"
            if payload.get("session_id") == "codex-thread-1"
            else None
        ),
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
    monkeypatch.setattr(
        "yoke_harness.model_attestation._codex_facts",
        lambda _payload: SessionModelFacts(),
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
    # Nothing attested and nothing requested: neither key ships, because a
    # null in the served slot would read as a provider report.
    assert "model" not in captured["body"]
    assert captured["body"]["entrypoint"] is None
