"""Tests for the explicit session-end orphaned-tool-call sweep.

Covers the pure helper and the destructive end_session branch. Stop
cleanup intentionally skips the sweep; sentinel payload assertions stay
on the helper itself so the slow path remains independently covered.

Post telemetry-only-events state model: orphans are OPEN ``session_tool_calls`` rows
(``completed_at IS NULL``). The sweep closes them in place AND still
synthesizes the sentinel ``HarnessToolCallCompleted`` telemetry rows
(operator-locked R3: both surfaces are maintained; readers consume only
the table).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.domain.events_tool_call_outcome import OUTCOME_INTERRUPTED
from yoke_core.domain.sessions import (
    claim_work,
    end_session,
    end_session_if_empty,
)
from yoke_core.domain.sessions_orphan_tool_call_sweep import (
    LIFECYCLE_REASONS,
    OrphanSweepReason,
    build_sentinel_reason,
    sweep_orphaned_tool_calls,
)
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements
from runtime.api.test_sessions import (  # noqa: F401
    _register,
    conn,
)


EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    source_type TEXT,
    session_id TEXT NOT NULL,
    severity TEXT,
    event_kind TEXT,
    event_type TEXT,
    event_name TEXT,
    event_outcome TEXT,
    service TEXT,
    project_id INTEGER DEFAULT 1 REFERENCES projects(id),
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
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_tool_use_id_dedup
    ON events(tool_use_id, event_name) WHERE tool_use_id IS NOT NULL;
"""


def _seed_events(c) -> None:
    apply_ddl_statements(c, EVENTS_SCHEMA)
    c.commit()


def _now_iso(offset_s: int = 0) -> str:
    when = datetime.now(timezone.utc) + timedelta(seconds=offset_s)
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def _insert_open_call(c, *, session_id, tool_use_id, tool_name="Bash",
                      started_at=None):
    """Open a session_tool_calls row (what observe_pre records on Started)."""
    started_at = started_at or _now_iso()
    c.execute(
        """INSERT INTO session_tool_calls
           (session_id, tool_use_id, tool_name, started_at)
           VALUES (%s, %s, %s, %s)""",
        (session_id, tool_use_id, tool_name, started_at),
    )
    c.commit()


def _close_call(c, *, session_id, tool_use_id, outcome="completed"):
    """Close the row (what the observe pipeline does on Completed/Failed)."""
    c.execute(
        """UPDATE session_tool_calls SET completed_at = %s, outcome = %s
           WHERE session_id = %s AND tool_use_id = %s""",
        (_now_iso(), outcome, session_id, tool_use_id),
    )
    c.commit()


def _open_rows(c, session_id: str) -> list:
    return list(c.execute(
        """SELECT tool_use_id, outcome FROM session_tool_calls
           WHERE session_id = %s AND completed_at IS NULL""",
        (session_id,),
    ))


def _sentinels(c, session_id: str) -> list:
    return list(c.execute(
        """SELECT * FROM events WHERE session_id = %s
             AND event_name = 'HarnessToolCallCompleted'
             AND event_outcome = %s""",
        (session_id, OUTCOME_INTERRUPTED),
    ))


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------


class TestOrphanSweepReason:
    def test_as_dict_returns_four_named_fields(self):
        r = OrphanSweepReason(
            ending_session_id="sess-A",
            sentinel_emitted_at="2026-05-19T10:00:00.000Z",
            original_started_at="2026-05-19T09:59:00.000Z",
            lifecycle_reason="session_end_destructive",
        )
        d = r.as_dict()
        assert set(d) == {"ending_session_id", "sentinel_emitted_at",
                          "original_started_at", "lifecycle_reason"}
        assert d["lifecycle_reason"] in LIFECYCLE_REASONS

    def test_build_sentinel_reason_copies_started_at(self, conn):
        _insert_open_call(conn, session_id="sess-A", tool_use_id="tu-1",
                          started_at="2026-05-19T09:00:00.000Z")
        row = conn.execute(
            "SELECT * FROM session_tool_calls WHERE tool_use_id = 'tu-1'"
        ).fetchone()
        reason = build_sentinel_reason(row, "sess-A", "session_end_destructive")
        assert reason.original_started_at == "2026-05-19T09:00:00.000Z"
        assert reason.ending_session_id == "sess-A"
        assert reason.lifecycle_reason == "session_end_destructive"


# ---------------------------------------------------------------------------
# Direct sweep invocation
# ---------------------------------------------------------------------------


class TestSweep:
    def test_rejects_unknown_lifecycle_reason(self, conn):
        with pytest.raises(ValueError):
            sweep_orphaned_tool_calls(conn, session_id="sess-A",
                                      lifecycle_reason="bogus")

    def test_one_orphan_one_matched_emits_one_sentinel(self, conn):
        _seed_events(conn)
        _insert_open_call(conn, session_id="sess-A", tool_use_id="tu-orphan")
        _insert_open_call(conn, session_id="sess-A", tool_use_id="tu-matched")
        _close_call(conn, session_id="sess-A", tool_use_id="tu-matched")

        result = sweep_orphaned_tool_calls(conn, session_id="sess-A",
                                           lifecycle_reason="session_end_destructive")
        assert result["matched"] == 1
        assert result["skipped_null_tool_use_id"] == 0
        assert len(result["sentinel_event_ids"]) == 1
        rows = _sentinels(conn, "sess-A")
        assert len(rows) == 1
        assert rows[0]["tool_use_id"] == "tu-orphan"
        assert rows[0]["event_outcome"] == OUTCOME_INTERRUPTED
        assert rows[0]["exit_code"] is None
        # The state row is closed with the interrupted outcome (R3).
        assert _open_rows(conn, "sess-A") == []
        closed = conn.execute(
            "SELECT outcome FROM session_tool_calls "
            "WHERE session_id = 'sess-A' AND tool_use_id = 'tu-orphan'"
        ).fetchone()
        assert closed["outcome"] == OUTCOME_INTERRUPTED

    def test_closed_row_is_not_swept(self, conn):
        _seed_events(conn)
        _insert_open_call(conn, session_id="sess-A", tool_use_id="tu-failed")
        _close_call(conn, session_id="sess-A", tool_use_id="tu-failed",
                    outcome="failed")
        result = sweep_orphaned_tool_calls(conn, session_id="sess-A",
                                           lifecycle_reason="session_end_destructive")
        assert result["matched"] == 0
        assert _sentinels(conn, "sess-A") == []
        kept = conn.execute(
            "SELECT outcome FROM session_tool_calls "
            "WHERE session_id = 'sess-A' AND tool_use_id = 'tu-failed'"
        ).fetchone()
        assert kept["outcome"] == "failed"

    def test_rows_close_even_without_events_table(self, conn):
        # No events table: the state side still closes; no sentinel rows.
        _insert_open_call(conn, session_id="sess-A", tool_use_id="tu-orphan")
        result = sweep_orphaned_tool_calls(conn, session_id="sess-A",
                                           lifecycle_reason="session_end_destructive")
        assert result["matched"] == 1
        assert result["sentinel_event_ids"] == []
        assert _open_rows(conn, "sess-A") == []

    def test_sentinel_payload_carries_four_named_fields(self, conn):
        _seed_events(conn)
        _insert_open_call(conn, session_id="sess-A", tool_use_id="tu-1",
                          started_at="2026-05-19T09:00:00.000Z")
        sweep_orphaned_tool_calls(conn, session_id="sess-A",
                                  lifecycle_reason="stop_hook_destructive")
        row = _sentinels(conn, "sess-A")[0]
        env = json.loads(row["envelope"])
        reason = env["context"]["detail"]["sentinel_reason"]
        assert set(reason) == {"ending_session_id", "sentinel_emitted_at",
                               "original_started_at", "lifecycle_reason"}
        assert reason["ending_session_id"] == "sess-A"
        assert reason["lifecycle_reason"] == "stop_hook_destructive"
        assert reason["original_started_at"] == "2026-05-19T09:00:00.000Z"
        assert reason["sentinel_emitted_at"]
        assert env["context"]["detail"]["tool_name"] == "Bash"

    def test_sentinel_project_id_resolves_from_session_registration(self, conn):
        _seed_events(conn)
        _register(conn, session_id="sess-P", project_id=2)
        _insert_open_call(conn, session_id="sess-P", tool_use_id="tu-p1")
        sweep_orphaned_tool_calls(conn, session_id="sess-P",
                                  lifecycle_reason="session_end_destructive")
        rows = _sentinels(conn, "sess-P")
        assert len(rows) == 1
        assert rows[0]["project_id"] == 2

    def test_sentinel_project_id_falls_back_for_unregistered_session(self, conn):
        _seed_events(conn)
        _insert_open_call(conn, session_id="sess-U", tool_use_id="tu-u1")
        sweep_orphaned_tool_calls(conn, session_id="sess-U",
                                  lifecycle_reason="session_end_destructive")
        rows = _sentinels(conn, "sess-U")
        assert len(rows) == 1
        assert rows[0]["project_id"] == 1

    def test_sweep_is_idempotent(self, conn):
        _seed_events(conn)
        _insert_open_call(conn, session_id="sess-A", tool_use_id="tu-orphan")

        first = sweep_orphaned_tool_calls(conn, session_id="sess-A",
                                          lifecycle_reason="session_end_destructive")
        assert first["matched"] == 1

        before = conn.execute("SELECT COUNT(*) FROM events WHERE session_id = %s",
                              ("sess-A",)).fetchone()[0]
        second = sweep_orphaned_tool_calls(conn, session_id="sess-A",
                                           lifecycle_reason="session_end_destructive")
        after = conn.execute("SELECT COUNT(*) FROM events WHERE session_id = %s",
                             ("sess-A",)).fetchone()[0]
        assert second["sentinel_event_ids"] == []
        assert second["matched"] == 0
        assert before == after


# ---------------------------------------------------------------------------
# Live wiring — destructive end_session
# ---------------------------------------------------------------------------


class TestEndSessionDestructiveBranch:
    def test_destructive_end_fires_sweep(self, conn):
        _seed_events(conn)
        _register(conn, session_id="sess-D")
        claim_work(conn, session_id="sess-D", item_id="100")
        _insert_open_call(conn, session_id="sess-D", tool_use_id="tu-orphan-d")

        # Backdate every activity signal so the destructive guard chooses
        # non-deferred under canonical liveness.
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = %s WHERE session_id = %s",
            ("2026-01-01T00:00:00.000Z", "sess-D"),
        )
        conn.execute(
            """UPDATE work_claims
               SET last_heartbeat = %s, claimed_at = %s
               WHERE session_id = %s""",
            ("2026-01-01T00:00:00.000Z",
             "2026-01-01T00:00:00.000Z",
             "sess-D"),
        )
        conn.commit()

        end_session(conn, "sess-D", release_claims=True)

        rows = _sentinels(conn, "sess-D")
        assert len(rows) == 1
        env = json.loads(rows[0]["envelope"])
        assert env["context"]["detail"]["sentinel_reason"]["lifecycle_reason"] == (
            "session_end_destructive"
        )
        assert rows[0]["tool_use_id"] == "tu-orphan-d"
        assert _open_rows(conn, "sess-D") == []

    def test_non_destructive_end_with_no_claims_does_not_sweep(self, conn):
        # release_claims=False AND no claim held — neither branch fires sweep.
        _seed_events(conn)
        _register(conn, session_id="sess-N")
        _insert_open_call(conn, session_id="sess-N", tool_use_id="tu-orphan-n")
        end_session(conn, "sess-N", release_claims=False)
        assert _sentinels(conn, "sess-N") == []
        assert len(_open_rows(conn, "sess-N")) == 1


# ---------------------------------------------------------------------------
# Stop cleanup keeps the lifecycle close cheap.
# ---------------------------------------------------------------------------


class TestEndSessionIfEmpty:
    def test_idle_auto_end_skips_sweep(self, conn):
        _seed_events(conn)
        _register(conn, session_id="sess-I")
        _insert_open_call(conn, session_id="sess-I", tool_use_id="tu-orphan-i")
        result = end_session_if_empty(conn, "sess-I")
        assert result["status"] == "ended"

        assert _sentinels(conn, "sess-I") == []
        assert len(_open_rows(conn, "sess-I")) == 1


# ---------------------------------------------------------------------------
# AC-9 first-class column audit count
# ---------------------------------------------------------------------------


class TestFirstClassColumnsAuditQuery:
    def test_count_of_interrupted_rows_matches_expected(self, conn):
        _seed_events(conn)
        _register(conn, session_id="sess-Q")
        _insert_open_call(conn, session_id="sess-Q", tool_use_id="tu-q1")
        _insert_open_call(conn, session_id="sess-Q", tool_use_id="tu-q2")
        _insert_open_call(conn, session_id="sess-Q", tool_use_id="tu-q3")
        _close_call(conn, session_id="sess-Q", tool_use_id="tu-q2")
        sweep_orphaned_tool_calls(
            conn, session_id="sess-Q", lifecycle_reason="session_idle_auto_ended"
        )
        count = conn.execute(
            """SELECT COUNT(*) FROM events WHERE session_id = %s
                 AND event_name = 'HarnessToolCallCompleted'
                 AND event_outcome = %s""",
            ("sess-Q", OUTCOME_INTERRUPTED),
        ).fetchone()[0]
        assert count == 2
        interrupted = conn.execute(
            """SELECT COUNT(*) FROM session_tool_calls
               WHERE session_id = %s AND outcome = %s""",
            ("sess-Q", OUTCOME_INTERRUPTED),
        ).fetchone()[0]
        assert interrupted == 2
