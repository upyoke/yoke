"""Tests for the cmd_claim TOCTOU recheck path (the race shape).

Covers the three reclaim shapes called out by AC-5:

(a) genuinely stale — both heartbeat and last-event older than TTL, and
    stay older across the recheck. Reclaim succeeds, ``WorkReclaimed``
    fires, original claim row is released.
(b) snapshot says stale but the original session has a fresh
    ``last_heartbeat`` at the recheck. Reclaim is aborted,
    ``ReclaimAborted`` fires, the original claim row is left untouched.
(c) original session is ``ended_at IS NOT NULL``. Reclaim succeeds
    regardless of activity recency.

The fixtures supply an ``events`` table that carries both a top-level
``session_id`` column (used by ``cmd_claim``'s snapshot subquery) and a
JSON ``envelope`` column (used by the shared activity classifier's
``_max_tool_event_at`` helper) so the snapshot and recheck see the same
underlying tool-call rows.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.test_sessions import _register  # noqa: F401  (plain helper)
from runtime.api.sessions_api_stale_test_helpers import (
    _ago_minutes,
    _now_literal,
    apply_ddl_statements,
    conn,  # noqa: F401  (backend-aware pytest fixture)
)


# Events table fixture used by cmd_claim's conflict snapshot AND by the
# shared activity classifier's _max_tool_event_at helper. Carries both a
# top-level ``session_id`` column and a JSON ``envelope`` column.
#
# The empty ``event_registry`` table lets the native event emitter's
# retired-name guard (``assert_event_name_not_retired``) run its
# ``SELECT status FROM event_registry`` cleanly: on SQLite a missing table
# raises ``OperationalError`` and the guard fails open, but on Postgres the
# missing relation poisons the surrounding transaction (the guard catches only
# ``sqlite3.OperationalError``), which then breaks ``cmd_claim``'s next query.
_EVENTS_TABLE_FOR_CLAIM_RACE = """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        event_id TEXT UNIQUE,
        event_name TEXT NOT NULL,
        event_kind TEXT,
        event_type TEXT NOT NULL DEFAULT 'system',
        source_type TEXT,
        session_id TEXT,
        severity TEXT DEFAULT 'INFO',
        event_outcome TEXT,
        user_id TEXT,
        org_id TEXT,
        environment TEXT,
        service TEXT,
        project_id INTEGER,
        actor_id INTEGER,
        item_id TEXT,
        task_num INTEGER,
        agent TEXT,
        tool_name TEXT,
        duration_ms INTEGER,
        exit_code INTEGER,
        trace_id TEXT,
        parent_id TEXT,
        anomaly_flags TEXT,
        tool_use_id TEXT,
        turn_id TEXT,
        hook_event_name TEXT,
        envelope TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS event_registry (
        event_name TEXT PRIMARY KEY,
        owner_service TEXT,
        status TEXT
    );
"""


@pytest.fixture
def race_conn(conn):
    apply_ddl_statements(conn, _EVENTS_TABLE_FOR_CLAIM_RACE)
    return conn


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


def _seed_holder_with_claim(
    conn,
    *,
    holder_session_id: str,
    item_id: int,
    holder_heartbeat_ago_min: int,
    claim_heartbeat_ago_min: int,
    holder_ended_at: str = None,
    holder_executor: str = "claude-code",
):
    """Seed a holder session and its existing item claim."""
    _register(conn, session_id=holder_session_id, executor=holder_executor)
    holder_hb = (
        _ago_minutes(holder_heartbeat_ago_min)
        if holder_heartbeat_ago_min > 0 else _now_literal()
    )
    conn.execute(
        """UPDATE harness_sessions
           SET offered_at = %s, last_heartbeat = %s, ended_at = %s
           WHERE session_id = %s""",
        (holder_hb, holder_hb, holder_ended_at, holder_session_id),
    )
    claim_hb = (
        _ago_minutes(claim_heartbeat_ago_min)
        if claim_heartbeat_ago_min > 0 else _now_literal()
    )
    conn.execute(
        """INSERT INTO work_claims
           (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
           VALUES (%s, 'item', %s, 'exclusive', %s, %s)""",
        (holder_session_id, item_id, claim_hb, claim_hb),
    )
    conn.commit()


def _attempt_claim(conn, attempting_session_id: str, item_id: int):
    """Run cmd_claim from a fresh session and return its outcome."""
    _register(conn, session_id=attempting_session_id)
    from runtime.harness.harness_sessions_claims_acquire import cmd_claim
    return cmd_claim(
        conn,
        attempting_session_id,
        "item",
        item_id=item_id,
    )


def _read_events(conn, event_name: str):
    rows = conn.execute(
        "SELECT envelope FROM events WHERE event_name = %s ORDER BY id",
        (event_name,),
    ).fetchall()
    return [json.loads(row["envelope"] or "{}") for row in rows]


class TestCmdClaimReclaimRace:
    """AC-5 / AC-1 — TOCTOU recheck inside cmd_claim's reclaim block."""

    def test_genuinely_stale_holder_is_reclaimed(self, race_conn):
        """AC-5(a): heartbeat + tool event both stale → reclaim succeeds."""
        c = race_conn
        _seed_holder_with_claim(
            c,
            holder_session_id="holder-A",
            item_id=4001,
            holder_heartbeat_ago_min=30,
            claim_heartbeat_ago_min=30,
        )
        _insert_tool_event(c, "holder-A", ago_minutes=25)

        result = _attempt_claim(c, "challenger-B", item_id=4001)

        # B took over the claim.
        assert "Claimed:" in result
        # Holder's claim row was released with reason='reclaimed'.
        old_row = c.execute(
            """SELECT released_at, release_reason FROM work_claims
               WHERE session_id = 'holder-A' AND item_id = 4001""",
        ).fetchone()
        assert old_row["released_at"] is not None
        assert old_row["release_reason"] == "reclaimed"
        # WorkReclaimed event fired; ReclaimAborted did not.
        reclaimed = _read_events(c, "WorkReclaimed")
        aborted = _read_events(c, "ReclaimAborted")
        assert len(reclaimed) == 1
        assert len(aborted) == 0

    def test_fresh_heartbeat_aborts_reclaim(self, race_conn):
        """AC-5(b): claim row stale but holder session heartbeated → abort."""
        c = race_conn
        # Snapshot uses wc.last_heartbeat (claim row, stale). The recheck
        # uses harness_sessions.last_heartbeat (holder session, fresh).
        # The mismatch is the silent-collision shape.
        _seed_holder_with_claim(
            c,
            holder_session_id="holder-A",
            item_id=4002,
            holder_heartbeat_ago_min=1,        # session heartbeated recently
            claim_heartbeat_ago_min=30,        # claim row is stale
        )
        _insert_tool_event(c, "holder-A", ago_minutes=25)

        with pytest.raises(PermissionError, match="already claimed by session"):
            _attempt_claim(c, "challenger-B", item_id=4002)

        # AC-4: holder's row stays untouched.
        old_row = c.execute(
            """SELECT released_at, release_reason FROM work_claims
               WHERE session_id = 'holder-A' AND item_id = 4002""",
        ).fetchone()
        assert old_row["released_at"] is None
        assert old_row["release_reason"] is None

        # ReclaimAborted fired with the canonical payload shape.
        aborted = _read_events(c, "ReclaimAborted")
        assert len(aborted) == 1
        detail = aborted[0]["context"]["detail"]
        assert detail["scope"] == "item_claim"
        assert detail["original_session_id"] == "holder-A"
        assert detail["attempting_session_id"] == "challenger-B"
        assert detail["abort_reason"] == "fresh"
        assert detail["effective_ttl_minutes"] == 20
        assert detail["executor"] == "claude-code"
        assert "original_session_last_heartbeat" in detail
        assert "original_session_last_event_at" in detail
        assert detail["target_kind"] == "item"
        # WorkReclaimed did NOT fire (mutation was aborted).
        reclaimed = _read_events(c, "WorkReclaimed")
        assert len(reclaimed) == 0

    def test_fresh_claim_heartbeat_is_not_a_reclaim_candidate(self, race_conn):
        """AC-13: fresh work_claims heartbeat prevents reclaim selection."""
        c = race_conn
        _seed_holder_with_claim(
            c,
            holder_session_id="holder-A",
            item_id=4004,
            holder_heartbeat_ago_min=30,
            claim_heartbeat_ago_min=1,
        )
        _insert_tool_event(c, "holder-A", ago_minutes=25)

        with pytest.raises(PermissionError, match="already claimed by session"):
            _attempt_claim(c, "challenger-B", item_id=4004)

        old_row = c.execute(
            """SELECT released_at, release_reason FROM work_claims
               WHERE session_id = 'holder-A' AND item_id = 4004""",
        ).fetchone()
        assert old_row["released_at"] is None
        assert old_row["release_reason"] is None
        # No abort event is expected: the row was not snapshot-eligible.
        aborted = _read_events(c, "ReclaimAborted")
        assert len(aborted) == 0

    def test_ended_holder_is_reclaimed_regardless_of_recent_activity(self, race_conn):
        """AC-5(c): ended_at is the terminal short-circuit."""
        c = race_conn
        _seed_holder_with_claim(
            c,
            holder_session_id="holder-A",
            item_id=4003,
            holder_heartbeat_ago_min=1,        # would be fresh
            claim_heartbeat_ago_min=1,
            holder_ended_at=_now_literal(),    # but ended_at is set
        )
        _insert_tool_event(c, "holder-A", ago_minutes=1)

        result = _attempt_claim(c, "challenger-B", item_id=4003)

        assert "Claimed:" in result
        old_row = c.execute(
            """SELECT released_at, release_reason FROM work_claims
               WHERE session_id = 'holder-A' AND item_id = 4003""",
        ).fetchone()
        assert old_row["released_at"] is not None
        assert old_row["release_reason"] == "reclaimed"
        reclaimed = _read_events(c, "WorkReclaimed")
        aborted = _read_events(c, "ReclaimAborted")
        assert len(reclaimed) == 1
        assert len(aborted) == 0
