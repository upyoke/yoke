"""Claude presentation observation and quiet transition persistence."""

from __future__ import annotations

import json
import sqlite3

from yoke_core.domain.session_presentation_observation import (
    record_session_presentation,
)
from yoke_harness.hooks.identity_claude_presentation import (
    observe_claude_presentation,
)


SESSION_ID = "12345678-1234-4234-8234-123456789abc"


def _state_file(tmp_path, state):
    path = tmp_path / "jobs" / "12345678" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def test_observer_reports_remote_control_without_owner_or_frontend(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    _state_file(
        tmp_path,
        {
            "sessionId": SESSION_ID,
            "bridgeSessionId": "bridge-private-id",
            "bridgeOutboundOnly": False,
            "bridgeOwnerAccountUuid": "owner-private-id",
        },
    )

    observed = observe_claude_presentation(
        "claude-code",
        {"session_id": SESSION_ID},
    )

    assert observed["presentation_surface"] == "remote-control"
    assert observed["presentation_state"] == "attached"
    assert observed["presentation_mode"] == "bidirectional"
    assert observed["presentation_source"] == "claude-job-state"
    assert "bridge" not in repr(observed).lower()
    assert "frontend" not in observed


def test_observer_records_proven_absence_and_rejects_wrong_session(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    path = _state_file(tmp_path, {"sessionId": SESSION_ID})
    observed = observe_claude_presentation("claude", {"session_id": SESSION_ID})
    assert observed["presentation_state"] == "not-attached"
    assert observed["presentation_surface"] is None

    path.write_text(json.dumps({"sessionId": "another-session"}), encoding="utf-8")
    assert observe_claude_presentation("claude", {"session_id": SESSION_ID}) == {}


def test_persistence_writes_only_material_ordered_transitions():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, "
        "presentation_surface TEXT, presentation_state TEXT, "
        "presentation_mode TEXT, presentation_source TEXT, "
        "presentation_observed_at TEXT)"
    )
    conn.execute("INSERT INTO harness_sessions (session_id) VALUES (?)", (SESSION_ID,))
    attached = {
        "presentation_surface": "remote-control",
        "presentation_state": "attached",
        "presentation_mode": "bidirectional",
        "presentation_source": "claude-job-state",
        "presentation_observed_at": "2026-08-28T18:00:00Z",
    }

    assert record_session_presentation(
        conn, session_id=SESSION_ID, payload_json=json.dumps(attached)
    )
    assert not record_session_presentation(
        conn, session_id=SESSION_ID, payload_json=json.dumps(attached)
    )
    stale = {
        **attached,
        "presentation_surface": None,
        "presentation_state": "not-attached",
        "presentation_mode": None,
        "presentation_observed_at": "2026-08-28T17:59:59Z",
    }
    assert not record_session_presentation(
        conn, session_id=SESSION_ID, payload_json=json.dumps(stale)
    )
