# ruff: noqa: F401, F811
"""Tests for ``reclaim_stale_item_claims`` final-recheck path.

Item-scoped sweep at session-offer time must use the same activity
signals as ``cmd_claim`` and ``clean_stale_harness_sessions``: when the
holder has stale heartbeat but fresh tool-call activity, the sweep
aborts the reclaim and emits ``ReclaimAborted`` with
``scope='item_claim'``.
"""

from __future__ import annotations

import pytest

from runtime.api.test_sessions import _register  # noqa: F401  (plain helper)
from runtime.api.sessions_api_stale_test_helpers import (
    _ago_minutes,
    apply_ddl_statements,
    conn,  # noqa: F401  (backend-aware pytest fixture)
)
from yoke_core.domain.work_claim_targets import make_item_target


_EVENTS_TABLE = """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        event_id TEXT,
        event_name TEXT NOT NULL,
        event_kind TEXT,
        event_type TEXT NOT NULL DEFAULT 'system',
        source_type TEXT,
        session_id TEXT,
        severity TEXT DEFAULT 'INFO',
        event_outcome TEXT,
        service TEXT,
        project_id INTEGER,
        item_id TEXT,
        task_num INTEGER,
        agent TEXT,
        tool_name TEXT,
        duration_ms INTEGER,
        trace_id TEXT,
        anomaly_flags TEXT,
        tool_use_id TEXT,
        turn_id TEXT,
        hook_event_name TEXT,
        client_timing_id TEXT,
        envelope TEXT,
        created_at TEXT NOT NULL
    );
"""


@pytest.fixture
def conn_with_events(conn):
    apply_ddl_statements(conn, _EVENTS_TABLE)
    return conn


def _seed_holder(
    conn,
    *,
    holder_session_id: str,
    item_id: int,
    holder_heartbeat_ago_min: int,
    claim_heartbeat_ago_min: int,
    executor: str = "claude-code",
):
    _register(conn, session_id=holder_session_id, executor=executor)
    holder_hb = _ago_minutes(holder_heartbeat_ago_min)
    conn.execute(
        """UPDATE harness_sessions
           SET offered_at = %s, last_heartbeat = %s
           WHERE session_id = %s""",
        (holder_hb, holder_hb, holder_session_id),
    )
    claim_hb = _ago_minutes(claim_heartbeat_ago_min)
    target = make_item_target(item_id)
    conn.execute(
        """INSERT INTO work_claims
           (session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat)
           VALUES (%s, %s, %s, 'exclusive', %s, %s)""",
        (holder_session_id, target.kind, target.scope_json(), claim_hb, claim_hb),
    )
    conn.commit()


def _claim_row(conn, session_id: str, item_id: int):
    target = make_item_target(item_id)
    return conn.execute(
        "SELECT released_at, release_reason FROM work_claims "
        "WHERE session_id = %s AND target_kind = %s AND scope = %s",
        (session_id, target.kind, target.scope_json()),
    ).fetchone()


def _insert_tool_event(conn, session_id: str, ago_minutes: int) -> None:
    """Stamp the tool-activity columns the observe pipeline maintains."""
    ts = _ago_minutes(ago_minutes)
    conn.execute(
        """UPDATE harness_sessions
           SET last_tool_call_at = %s,
               tool_call_count = COALESCE(tool_call_count, 0) + 1
           WHERE session_id = %s""",
        (ts, session_id),
    )
    conn.commit()


def _capture_session_events(monkeypatch):
    """Patch ``sessions_analytics._emit_session_event`` to capture calls.

    The ``_emit_session_event`` path does not thread the test connection
    through to the events table (events go to the default DB resolver).
    Capturing the call lets tests assert on ReclaimAborted payloads
    without depending on a full production events-table fixture.
    """
    captured = []
    from yoke_core.domain import sessions_render_reclaim as _srr

    real_emit = _srr._sa._emit_session_event

    def capture(
        event_name,
        *,
        session_id,
        item_id=None,
        task_num=None,
        context=None,
        outcome="completed",
    ):
        captured.append(
            {
                "event_name": event_name,
                "session_id": session_id,
                "item_id": item_id,
                "task_num": task_num,
                "context": context,
            }
        )
        return real_emit(
            event_name,
            session_id=session_id,
            item_id=item_id,
            task_num=task_num,
            context=context,
            outcome=outcome,
        )

    monkeypatch.setattr(_srr._sa, "_emit_session_event", capture)
    return captured


class TestReclaimStaleItemClaimsRecheck:
    """Same activity signals as cmd_claim and clean_stale_harness_sessions."""

    def test_reclaims_when_no_recent_tool_activity(self, conn_with_events):
        c = conn_with_events
        _seed_holder(
            c,
            holder_session_id="holder-A",
            item_id=5001,
            holder_heartbeat_ago_min=30,
            claim_heartbeat_ago_min=30,
        )

        from yoke_core.domain.sessions import reclaim_stale_item_claims

        released = reclaim_stale_item_claims(c, "5001", stale_threshold_minutes=10)

        assert released == 1
        row = _claim_row(c, "holder-A", 5001)
        assert row["released_at"] is not None
        assert row["release_reason"] == "reclaimed"

    def test_reclaim_releases_the_holder_item_focus(self, conn_with_events):
        """A reclaimed holder stops reading as working the item it lost."""
        from yoke_core.domain.sessions import (
            reclaim_stale_item_claims,
            set_current_item,
        )

        c = conn_with_events
        _seed_holder(
            c,
            holder_session_id="holder-focus",
            item_id=5010,
            holder_heartbeat_ago_min=30,
            claim_heartbeat_ago_min=30,
        )
        set_current_item(c, "holder-focus", "5010")

        assert reclaim_stale_item_claims(c, "5010", stale_threshold_minutes=10) == 1

        row = c.execute(
            "SELECT current_item_id, recent_item_id FROM harness_sessions "
            "WHERE session_id = %s",
            ("holder-focus",),
        ).fetchone()
        assert row["current_item_id"] is None
        assert str(row["recent_item_id"]) == "5010"

    def test_aborted_reclaim_leaves_the_holder_focus_alone(
        self,
        conn_with_events,
        monkeypatch,
    ):
        """Focus follows the claim: a claim that survives keeps its focus."""
        from yoke_core.domain.sessions import (
            reclaim_stale_item_claims,
            set_current_item,
        )

        c = conn_with_events
        _seed_holder(
            c,
            holder_session_id="holder-fresh",
            item_id=5011,
            holder_heartbeat_ago_min=1,
            claim_heartbeat_ago_min=30,
        )
        set_current_item(c, "holder-fresh", "5011")
        _capture_session_events(monkeypatch)

        assert reclaim_stale_item_claims(c, "5011", stale_threshold_minutes=10) == 0

        focus = c.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id = %s",
            ("holder-fresh",),
        ).fetchone()["current_item_id"]
        assert str(focus) == "5011"

    def test_aborts_when_holder_session_heartbeat_is_fresh(
        self,
        conn_with_events,
        monkeypatch,
    ):
        """Stale claim heartbeat but fresh session heartbeat → abort."""
        c = conn_with_events
        _seed_holder(
            c,
            holder_session_id="holder-A",
            item_id=5002,
            holder_heartbeat_ago_min=1,  # session heartbeated recently
            claim_heartbeat_ago_min=30,  # claim row is stale (snapshot)
        )
        captured = _capture_session_events(monkeypatch)

        from yoke_core.domain.sessions import reclaim_stale_item_claims

        released = reclaim_stale_item_claims(c, "5002", stale_threshold_minutes=10)

        assert released == 0
        row = _claim_row(c, "holder-A", 5002)
        assert row["released_at"] is None
        assert row["release_reason"] is None

        aborted = [e for e in captured if e["event_name"] == "ReclaimAborted"]
        assert len(aborted) == 1
        ctx = aborted[0]["context"]
        assert ctx["scope"] == "item_claim"
        assert ctx["original_session_id"] == "holder-A"
        assert ctx["abort_reason"] == "fresh"
        assert ctx["reclaimed_by_item_offer"] is True

    def test_fresh_claim_heartbeat_is_not_a_reclaim_candidate(
        self,
        conn_with_events,
        monkeypatch,
    ):
        c = conn_with_events
        _seed_holder(
            c,
            holder_session_id="holder-A",
            item_id=5004,
            holder_heartbeat_ago_min=30,
            claim_heartbeat_ago_min=1,
        )
        captured = _capture_session_events(monkeypatch)

        from yoke_core.domain.sessions import reclaim_stale_item_claims

        released = reclaim_stale_item_claims(c, "5004", stale_threshold_minutes=10)

        assert released == 0
        row = _claim_row(c, "holder-A", 5004)
        assert row["released_at"] is None
        assert row["release_reason"] is None
        # No abort event is expected: the row was not snapshot-eligible.
        aborted = [e for e in captured if e["event_name"] == "ReclaimAborted"]
        assert len(aborted) == 0

    def test_aborts_when_recent_tool_event_exists(
        self,
        conn_with_events,
        monkeypatch,
    ):
        """Event-side: stale heartbeats but a fresh tool event → abort."""
        c = conn_with_events
        _seed_holder(
            c,
            holder_session_id="holder-A",
            item_id=5003,
            holder_heartbeat_ago_min=30,
            claim_heartbeat_ago_min=30,
        )
        _insert_tool_event(c, "holder-A", ago_minutes=2)
        captured = _capture_session_events(monkeypatch)

        from yoke_core.domain.sessions import reclaim_stale_item_claims

        released = reclaim_stale_item_claims(c, "5003", stale_threshold_minutes=10)

        assert released == 0
        aborted = [e for e in captured if e["event_name"] == "ReclaimAborted"]
        assert len(aborted) == 1
