# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.sessions_test_support import _register  # noqa: F401  (plain helper)

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
        created_at TIMESTAMPTZ NOT NULL
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
