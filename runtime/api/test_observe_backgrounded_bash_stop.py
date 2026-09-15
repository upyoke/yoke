"""Auto-backgrounded Bash PostToolUse keeps the pending session_tool_calls row.

The 3116 Claude result object carried structured ``backgroundTaskId`` and
``timedOutAfterMs`` (``interrupted`` was false). Tests drive that payload
through parse → envelope → insert_event, then read the same
``live_stop_block_reason`` fact the Stop gate consumes.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.domain.observe import (
    build_envelope,
    detect_anomalies,
    insert_event,
    parse_hook_event,
)
from yoke_core.domain.observe_pre import parse_pre_event
from yoke_core.domain.session_tool_call_projections import live_stop_block_reason
from yoke_core.hooks.types import HookContext, Outcome
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.observe_full_test_helpers import make_events_db_conn

SESSION = "sess-bg-bash"
BASH_ID = "toolu_0175wZiZKEVCd6jEiW2jNqGN"
READ_ID = "toolu_read_unrelated"

# Exact toolUseResult from the auto-backgrounded Bash at 02:30:31Z.
BACKGROUND_RESULT = {
    "stdout": "",
    "stderr": "",
    "interrupted": False,
    "isImage": False,
    "noOutputExpected": False,
    "backgroundTaskId": "bep007lkn",
    "timedOutAfterMs": 120000,
}

_SESSION_DDL = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    mode TEXT,
    last_tool_call_at TEXT,
    tool_call_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE session_tool_calls (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_use_id TEXT NOT NULL,
    tool_name TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    outcome TEXT,
    command_summary TEXT
);
CREATE UNIQUE INDEX idx_session_tool_calls_bg
    ON session_tool_calls(session_id, tool_use_id);
"""


@pytest.fixture
def conn():
    db = make_events_db_conn()
    apply_fixture_ddl(db, _SESSION_DDL)
    db.execute(
        "INSERT INTO harness_sessions (session_id, mode) VALUES (%s, %s)",
        (SESSION, "dash"),
    )
    db.commit()
    yield db
    db.close()


def _insert(conn, envelope) -> None:
    insert_event(conn, envelope)


def _start(conn, *, tool_use_id: str, tool_name: str, command: str | None = None):
    payload: dict = {
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "session_id": SESSION,
        "tool_input": {"command": command} if command else {"file_path": "/tmp/x"},
    }
    envelope = parse_pre_event(payload)
    assert envelope is not None
    _insert(conn, envelope)


def _post(conn, payload: dict) -> None:
    rec = parse_hook_event(payload, session_id=SESSION, hook_event="PostToolUse")
    assert rec is not None
    detect_anomalies(rec)
    _insert(conn, build_envelope(rec))


def _row(conn, tool_use_id: str):
    return conn.execute(
        "SELECT completed_at, outcome FROM session_tool_calls "
        "WHERE session_id = %s AND tool_use_id = %s",
        (SESSION, tool_use_id),
    ).fetchone()


def _background_payload() -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": "yoke watch pytest --impacted main --bounded"},
        "tool_response": dict(BACKGROUND_RESULT),
        "tool_use_id": BASH_ID,
        "session_id": SESSION,
    }


def test_parse_marks_background_task_id_pending() -> None:
    rec = parse_hook_event(_background_payload(), hook_event="PostToolUse")
    assert rec is not None
    assert rec.pending_local_command is True


def test_parse_does_not_infer_pending_from_timeout_prose() -> None:
    rec = parse_hook_event(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "sleep 200"},
            "tool_response": {
                "content": (
                    "Command did not complete within its 120s timeout and was "
                    "moved to the background (ID: bep007lkn)."
                )
            },
            "tool_use_id": BASH_ID,
        },
        hook_event="PostToolUse",
    )
    assert rec is not None
    assert rec.pending_local_command is False


def test_backgrounded_post_leaves_the_started_row_open(conn) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    row = _row(conn, BASH_ID)
    assert row is not None
    assert row[0] is None
    assert live_stop_block_reason(conn, SESSION) == gate.REASON_LIVE_COMMAND


def test_later_read_does_not_erase_pending_bash(conn) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    _start(conn, tool_use_id=READ_ID, tool_name="Read")
    _post(
        conn,
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/x"},
            "tool_response": {"content": "ok"},
            "tool_use_id": READ_ID,
            "session_id": SESSION,
        },
    )
    assert _row(conn, BASH_ID)[0] is None
    assert _row(conn, READ_ID)[0] is not None
    assert live_stop_block_reason(conn, SESSION) == gate.REASON_LIVE_COMMAND


def test_exit_code_post_settles_the_hold(conn) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    _post(
        conn,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "sleep 200"},
            "tool_response": {"content": "Exit code 0"},
            "tool_use_id": BASH_ID,
            "session_id": SESSION,
        },
    )
    assert _row(conn, BASH_ID)[0] is not None
    assert live_stop_block_reason(conn, SESSION) is None


def test_parked_session_drops_the_live_command_hold(conn) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    conn.execute(
        "UPDATE harness_sessions SET mode = %s WHERE session_id = %s",
        ("parked", SESSION),
    )
    conn.commit()
    assert live_stop_block_reason(conn, SESSION) is None


def test_two_stops_at_cap_stay_denied_while_bash_pending(conn, monkeypatch) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    emitted: list[dict] = []
    monkeypatch.setattr(conn, "close", lambda: None)
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: conn)
    monkeypatch.setattr(gate, "session_was_relay_launched", lambda *_a: True)
    monkeypatch.setattr(
        gate, "_live_claim", lambda *_a: {"item_id": 42, "status": "implementing"}
    )
    monkeypatch.setattr(gate, "_at_reinjection_cap", lambda *_a: True)
    monkeypatch.setattr(gate, "_emit_deferred", lambda **kw: emitted.append(kw))
    monkeypatch.setattr(
        gate,
        "_evidence_for",
        lambda _r: type("E", (), {"available": True, "question": False})(),
    )
    ctx = HookContext(
        event_name="Stop",
        executor_family="claude",
        executor_surface="cli",
        payload={"entrypoint": "cli"},
        session_id=SESSION,
        remote=True,
    )
    first = gate.evaluate(ctx)
    second = gate.evaluate(ctx)
    assert first.outcome is Outcome.DENY
    assert second.outcome is Outcome.DENY
    assert [entry["reason"] for entry in emitted] == [
        gate.REASON_LIVE_COMMAND,
        gate.REASON_LIVE_COMMAND,
    ]
    assert first.message == gate.LIVE_COMMAND_DIRECTIVE
