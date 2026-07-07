"""Tests for yoke_core.domain.observe_pre — PreToolUse hook engine.

Covers parse_pre_event, write_pre_event, and process_stdin. Exercises the
end-to-end insertion against an in-memory / tempfile DB so the extracted
module matches the behavior the previous shell heredoc delivered
(tool_use_id / hook_event_name / turn_id / session_id columns).

CLI subprocess coverage lives in test_observe_pre_cli.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.observe_pre import (
    evaluate,
    parse_pre_event,
    process_stdin,
    write_pre_event,
)
from runtime.api.fixtures.file_test_db import (
    apply_sql_script,
    connect_test_db,
    init_test_db,
)
from runtime.api.observe_test_helpers import _PROJECTS_DDL, _PROJECTS_SEED_DDL
from runtime.harness.hook_runner.types import HookContext, Next, Outcome


EVENTS_SCHEMA = _PROJECTS_DDL + "\n" + _PROJECTS_SEED_DDL + """
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    source_type TEXT,
    session_id TEXT,
    severity TEXT,
    event_kind TEXT,
    event_type TEXT,
    event_name TEXT,
    event_outcome TEXT,
    service TEXT,
    project_id INTEGER,
    item_id TEXT,
    task_num INTEGER,
    agent TEXT,
    tool_name TEXT,
    duration_ms INTEGER,
    exit_code INTEGER,
    anomaly_flags TEXT,
    tool_use_id TEXT,
    turn_id TEXT,
    hook_event_name TEXT,
    envelope TEXT,
    created_at TEXT
)
"""


@pytest.fixture
def tmp_db(tmp_path: Path):
    with init_test_db(tmp_path, apply_schema=_apply_events_schema) as db_path:
        yield str(db_path)


def _apply_events_schema() -> None:
    conn = db_backend.connect()
    try:
        apply_sql_script(conn, EVENTS_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _fetch_rows(db_path: str) -> list:
    conn = connect_test_db(db_path)
    try:
        return list(
            conn.execute(
                "SELECT * FROM events WHERE event_name='HarnessToolCallStarted'"
            )
        )
    finally:
        conn.close()


class TestParsePreEvent:
    def test_basic_payload_builds_envelope(self):
        envelope = parse_pre_event(
            {
                "tool_use_id": "tu-abc",
                "tool_name": "Bash",
                "session_id": "sess-1",
            }
        )
        assert envelope is not None
        assert envelope["event_name"] == "HarnessToolCallStarted"
        assert envelope["event_outcome"] == "started"
        assert envelope["severity"] == "INFO"
        assert envelope["hook_event_name"] == "PreToolUse"
        assert envelope["tool_use_id"] == "tu-abc"
        assert envelope["tool_name"] == "Bash"
        assert envelope["session_id"] == "sess-1"
        assert "turn_id" not in envelope  # absent when not in payload

    def test_turn_id_propagated_when_present(self):
        envelope = parse_pre_event(
            {
                "tool_use_id": "tu-def",
                "tool_name": "Read",
                "session_id": "sess-2",
                "turn_id": "turn-99",
            }
        )
        assert envelope is not None
        assert envelope["turn_id"] == "turn-99"

    def test_payload_cwd_propagated_when_present(self):
        envelope = parse_pre_event(
            {
                "tool_use_id": "tu-cwd",
                "tool_name": "Bash",
                "session_id": "sess-cwd",
                "cwd": "/repo/yoke/.worktrees/YOK-1",
            }
        )
        assert envelope is not None
        assert envelope["cwd"] == "/repo/yoke/.worktrees/YOK-1"

    def test_project_dir_used_as_cwd_fallback(self):
        envelope = parse_pre_event(
            {
                "tool_use_id": "tu-project-dir",
                "tool_name": "Bash",
                "project_dir": "/repo/yoke",
            }
        )
        assert envelope is not None
        assert envelope["cwd"] == "/repo/yoke"

    def test_explicit_cwd_wins_over_fallback_cwd(self):
        envelope = parse_pre_event(
            {"tool_use_id": "tu-fallback", "cwd": "/payload/cwd"},
            fallback_cwd="/record/cwd",
        )
        assert envelope is not None
        assert envelope["cwd"] == "/payload/cwd"

    def test_missing_tool_use_id_drops_event(self):
        envelope = parse_pre_event(
            {"tool_name": "Bash", "session_id": "sess-x"}
        )
        assert envelope is None

    def test_empty_tool_use_id_drops_event(self):
        envelope = parse_pre_event(
            {"tool_use_id": "", "tool_name": "Bash"}
        )
        assert envelope is None

    def test_missing_session_id_defaults_to_unknown(self):
        envelope = parse_pre_event(
            {"tool_use_id": "tu-xyz", "tool_name": "Write"}
        )
        assert envelope is not None
        assert envelope["session_id"] == "unknown"

    def test_non_dict_payload_returns_none(self):
        assert parse_pre_event(None) is None  # type: ignore[arg-type]
        assert parse_pre_event([]) is None  # type: ignore[arg-type]
        assert parse_pre_event("string") is None  # type: ignore[arg-type]

    def test_event_id_is_unique_uuid(self):
        e1 = parse_pre_event({"tool_use_id": "tu-1"})
        e2 = parse_pre_event({"tool_use_id": "tu-2"})
        assert e1 is not None and e2 is not None
        assert e1["event_id"] != e2["event_id"]
        # UUID4 string is 36 chars
        assert len(e1["event_id"]) == 36

    def test_event_time_is_iso_with_millis(self):
        envelope = parse_pre_event({"tool_use_id": "tu-time"})
        assert envelope is not None
        ts = envelope["event_time"]
        # Matches: YYYY-MM-DDTHH:MM:SS.mmmZ
        assert ts.endswith("Z")
        assert "T" in ts
        assert "." in ts


# ---------------------------------------------------------------------------
# write_pre_event — end-to-end DB insertion
# ---------------------------------------------------------------------------


class TestWritePreEvent:
    def test_populates_row_columns(self, tmp_db):
        envelope = parse_pre_event(
            {
                "tool_use_id": "tu-abc123",
                "tool_name": "Bash",
                "session_id": "sess-xyz",
            }
        )
        assert envelope is not None
        write_pre_event(tmp_db, envelope)

        rows = _fetch_rows(tmp_db)
        assert len(rows) == 1
        row = rows[0]
        assert row["tool_use_id"] == "tu-abc123"
        assert row["tool_name"] == "Bash"
        assert row["session_id"] == "sess-xyz"
        assert row["hook_event_name"] == "PreToolUse"
        assert row["event_name"] == "HarnessToolCallStarted"
        assert row["event_outcome"] == "started"
        assert row["severity"] == "INFO"
        assert row["turn_id"] is None

    def test_populates_turn_id_when_present(self, tmp_db):
        envelope = parse_pre_event(
            {
                "tool_use_id": "tu-def456",
                "tool_name": "Read",
                "session_id": "sess-abc",
                "turn_id": "turn-99",
            }
        )
        assert envelope is not None
        write_pre_event(tmp_db, envelope)

        rows = _fetch_rows(tmp_db)
        assert len(rows) == 1
        assert rows[0]["turn_id"] == "turn-99"

    def test_envelope_json_round_trips(self, tmp_db):
        envelope = parse_pre_event(
            {
                "tool_use_id": "tu-json",
                "tool_name": "Edit",
                "session_id": "sess-json",
                "turn_id": "turn-json",
            }
        )
        assert envelope is not None
        write_pre_event(tmp_db, envelope)

        rows = _fetch_rows(tmp_db)
        assert len(rows) == 1
        stored = json.loads(rows[0]["envelope"])
        assert stored["event_name"] == "HarnessToolCallStarted"
        assert stored["tool_use_id"] == "tu-json"
        assert stored["hook_event_name"] == "PreToolUse"

    def test_missing_db_path_is_silent_noop(self):
        # Explicit None / empty should not raise
        envelope = parse_pre_event({"tool_use_id": "tu-none"})
        assert envelope is not None
        write_pre_event("", envelope)  # silent no-op
        write_pre_event("/nonexistent/path/yoke.db", envelope)  # silent no-op

    def test_insert_without_events_table_is_silent(self, tmp_path):
        with init_test_db(tmp_path, apply_schema=lambda: None) as db_path:
            envelope = parse_pre_event({"tool_use_id": "tu-noev"})
            assert envelope is not None
            write_pre_event(db_path, envelope)  # should not raise


# ---------------------------------------------------------------------------
# process_stdin — full parse+write path from a raw JSON string
# ---------------------------------------------------------------------------


class TestProcessStdin:
    def test_happy_path_inserts_row(self, tmp_db):
        raw = json.dumps(
            {
                "tool_use_id": "tu-proc",
                "tool_name": "Bash",
                "session_id": "sess-proc",
            }
        )
        assert process_stdin(raw, tmp_db) is True

        rows = _fetch_rows(tmp_db)
        assert len(rows) == 1
        assert rows[0]["tool_use_id"] == "tu-proc"

    def test_empty_stdin_returns_false(self, tmp_db):
        assert process_stdin("", tmp_db) is False
        assert process_stdin("   ", tmp_db) is False
        assert _fetch_rows(tmp_db) == []

    def test_malformed_json_returns_false(self, tmp_db):
        assert process_stdin("{not json", tmp_db) is False
        assert _fetch_rows(tmp_db) == []

    def test_missing_tool_use_id_returns_false(self, tmp_db):
        raw = json.dumps({"tool_name": "Bash"})
        assert process_stdin(raw, tmp_db) is False
        assert _fetch_rows(tmp_db) == []

    def test_missing_db_path_returns_false(self, tmp_db):
        raw = json.dumps({"tool_use_id": "tu-nodb"})
        if db_backend.is_postgres():
            assert process_stdin(raw, None) is True
            assert process_stdin(raw, "") is True
            return
        assert process_stdin(raw, None) is False
        assert process_stdin(raw, "") is False


class TestTypedEvaluate:
    def test_evaluate_uses_hook_context_cwd_when_payload_lacks_cwd(
        self, tmp_db, monkeypatch
    ):
        monkeypatch.setattr(
            "yoke_core.domain.observe_pre._resolve_db_fallback",
            lambda: tmp_db,
        )
        decision = evaluate(
            HookContext(
                event_name="PreToolUse",
                executor_family="codex",
                executor_surface="codex-desktop",
                payload={
                    "tool_use_id": "tu-typed",
                    "tool_name": "Bash",
                    "session_id": "sess-typed",
                },
                tool_name="Bash",
                cwd="/repo/yoke/.worktrees/YOK-1819",
                session_id="sess-typed",
            )
        )

        assert decision.outcome is Outcome.NOOP
        assert decision.next is Next.CONTINUE
        rows = _fetch_rows(tmp_db)
        assert len(rows) == 1
        stored = json.loads(rows[0]["envelope"])
        assert stored["cwd"] == "/repo/yoke/.worktrees/YOK-1819"
