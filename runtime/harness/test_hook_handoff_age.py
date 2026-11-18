"""The evaluator stamps a hook's age at hand-off, after its local work."""

from __future__ import annotations

import json
import time

import pytest

from yoke_contracts.hook_observation_age import hook_age_ms


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_relay_hand_off_carries_age_since_client_start(monkeypatch, executor):
    from yoke_cli.commands.adapters import hook_inprocess as entry
    from yoke_cli.transport import https
    from yoke_contracts.hook_runner import folder_scope
    from yoke_harness.hooks import identity, relay

    sent = {}
    monkeypatch.setattr(folder_scope, "folder_scope", lambda stdin: "registered")
    monkeypatch.setattr(identity, "detect_executor", lambda: executor)
    monkeypatch.setattr(entry, "_touch_detached_resume", lambda: None)
    # Slow local work before hand-off (orientation) must count toward the age.
    monkeypatch.setattr(
        entry, "_session_orientation", lambda *a, **kw: time.sleep(0.2) or ""
    )
    monkeypatch.setattr(https, "resolve_https_connection", lambda: object())

    def capture(event, connection, **kwargs):
        sent["stdin"] = kwargs["stdin_data"]
        return 0

    monkeypatch.setattr(relay, "relay_hook_event", capture)
    started = time.monotonic() - 1.0
    payload = {"session_id": "s", "cwd": "/tmp", "transcript_path": "/tmp/t.jsonl"}
    assert entry.evaluate_inprocess(
        "SessionStart", json.dumps(payload), dry_run=False,
        cursor_invocation=executor == "cursor", client_started_monotonic=started,
    ) == 0
    assert hook_age_ms(sent["stdin"]) >= 1200
