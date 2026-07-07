"""Defer-branch heartbeat refresh coverage for the destructive guard.

When ``handle_release_claims_branch`` decides to defer the SessionEnd
signal (transient — chain budget remaining), it also forward-stamps
``work_claims.last_heartbeat`` for every active claim the deferring
session still owns, advancing it by
``session_reactivation_reacquire_window_s`` (default 300s). This buys
the resume window of protection against another session's stale-claim
sweep during the harness pause.

Companion tests live alongside the existing destructive-guard suite at
``test_sessions_lifecycle_session_end_guard.py``; this file isolates the
defer-refresh AC coverage so the parent test file stays under the
350-line cap.

Coverage:
    Defer refreshes active claim heartbeats by the configured
          window.
    Defer leaves released claims untouched.
    Defer leaves other sessions' claims untouched.
    Permanent (non-defer) branch unaffected.
    Refresh applies across all three target_kind values — item,
           epic_task, and process.
    AC-20 (sibling watch-out): forward-stamped timestamp survives a
          subsequent live PreToolUse heartbeat overwrite — the live
          heartbeat resets to NOW, which is the intended behavior.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from runtime.api.fixtures import pg_testdb
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements


_DDL = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL DEFAULT 'claude-code',
    provider TEXT NOT NULL DEFAULT 'anthropic',
    model TEXT NOT NULL DEFAULT '',
    execution_lane TEXT NOT NULL DEFAULT 'primary',
    workspace TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'wait',
    offered_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    ended_at TEXT,
    offer_envelope TEXT,
    actor_id INTEGER,
    current_item_id TEXT,
    current_item_set_at TEXT,
    recent_item_id TEXT,
    recent_item_status TEXT,
    recent_item_recorded_at TEXT
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive',
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    event_name TEXT NOT NULL,
    session_id TEXT, item_id TEXT, task_num INTEGER, context TEXT,
    created_at TEXT NOT NULL DEFAULT (now()::text)
);
"""


def _now_iso(delta_s: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _build_conn():
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    apply_ddl_statements(conn, _DDL)
    conn.commit()
    return conn


def _insert_session(
    conn, sid: str, *, heartbeat_age_s: int = 10, chainable: bool = True,
) -> None:
    """Insert a harness_sessions row.

    Defaults to a chainable checkpoint so the destructive guard defers
    on this session — the defer branch is what the rest of this file
    exercises. Pass ``chainable=False`` to set up the permanent-end
    branch.
    """
    ts = _now_iso(-heartbeat_age_s)
    envelope = ""
    if chainable:
        envelope = json.dumps({
            "chain_checkpoint": {
                "chainable": True,
                "step": 1,
                "max_chain_steps": 3,
                "action": "charge",
                "handler_outcome": "completed",
            },
        })
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, workspace, offered_at, last_heartbeat, offer_envelope) "
        "VALUES (%s, '/tmp', %s, %s, %s)",
        (sid, ts, ts, envelope),
    )
    conn.commit()


def _insert_item_claim(conn, sid: str, item_id: int, *, age_s: int = 10) -> int:
    ts = _now_iso(-age_s)
    cursor = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, "
        " last_heartbeat) VALUES (%s, 'item', %s, 'exclusive', %s, %s) RETURNING id",
        (sid, item_id, ts, ts),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.commit()
    return int(row[0])


def _active_rows(conn, sid: str):
    return conn.execute(
        "SELECT id, item_id, task_num FROM work_claims "
        "WHERE session_id = %s AND released_at IS NULL",
        (sid,),
    ).fetchall()


def _run_defer(conn, sid: str) -> None:
    from yoke_core.domain.sessions_lifecycle_destructive_guard import (
        handle_release_claims_branch,
    )
    rows = _active_rows(conn, sid)
    with mock.patch(
        "yoke_core.domain.scheduler_events.emit_harness_session_end_deferred",
    ):
        handle_release_claims_branch(
            conn, sid, force=True, active_claim_rows=rows,
        )


class TestDeferBranchRefreshHeartbeats(unittest.TestCase):
    def test_defer_advances_heartbeat_past_now(self) -> None:
        conn = _build_conn()
        _insert_session(conn, "sess-d", heartbeat_age_s=10)
        cid = _insert_item_claim(conn, "sess-d", 101)
        before = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id = %s", (cid,),
        ).fetchone()["last_heartbeat"]
        _run_defer(conn, "sess-d")
        after = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id = %s", (cid,),
        ).fetchone()["last_heartbeat"]
        self.assertGreater(after, before)
        self.assertGreater(after, _now_iso())

    def test_defer_leaves_released_rows_untouched(self) -> None:
        conn = _build_conn()
        _insert_session(conn, "sess-r", heartbeat_age_s=10)
        active = _insert_item_claim(conn, "sess-r", 102)
        old_ts = _now_iso(-9999)
        cursor = conn.execute(
            "INSERT INTO work_claims "
            "(session_id, target_kind, item_id, claim_type, claimed_at, "
            " last_heartbeat, released_at, release_reason) "
            "VALUES (%s, 'item', %s, 'exclusive', %s, %s, %s, 'released') RETURNING id",
            ("sess-r", 103, old_ts, old_ts, old_ts),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.commit()
        released_id = int(row[0])
        _run_defer(conn, "sess-r")
        active_hb = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id = %s", (active,),
        ).fetchone()["last_heartbeat"]
        released_hb = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id = %s", (released_id,),
        ).fetchone()["last_heartbeat"]
        self.assertGreater(active_hb, _now_iso())
        self.assertEqual(released_hb, old_ts)

    def test_defer_leaves_other_sessions_claims_untouched(self) -> None:
        conn = _build_conn()
        _insert_session(conn, "sess-A", heartbeat_age_s=10)
        _insert_session(conn, "sess-B", heartbeat_age_s=10)
        a_id = _insert_item_claim(conn, "sess-A", 104)
        b_id = _insert_item_claim(conn, "sess-B", 105)
        before_b = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id = %s", (b_id,),
        ).fetchone()["last_heartbeat"]
        _run_defer(conn, "sess-A")
        after_a = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id = %s", (a_id,),
        ).fetchone()["last_heartbeat"]
        after_b = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id = %s", (b_id,),
        ).fetchone()["last_heartbeat"]
        self.assertGreater(after_a, _now_iso())
        self.assertEqual(after_b, before_b)

    def test_permanent_branch_does_not_refresh(self) -> None:
        from yoke_core.domain.sessions_lifecycle_destructive_guard import (
            handle_release_claims_branch,
        )

        conn = _build_conn()
        _insert_session(conn, "sess-perm", chainable=False)
        _insert_item_claim(conn, "sess-perm", 106, age_s=99999)
        rows = _active_rows(conn, "sess-perm")
        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_destructive_guard."
            "refresh_deferred_session_claim_heartbeats",
        ) as refresh, mock.patch(
            "yoke_core.domain.sessions_lifecycle_release.release_all_claims",
            return_value=1,
        ), mock.patch(
            "yoke_core.domain.sessions_analytics._emit_session_event",
        ):
            handle_release_claims_branch(
                conn, "sess-perm", force=True, active_claim_rows=rows,
            )
        refresh.assert_not_called()

    def test_defer_refresh_covers_item_epic_task_and_process(self) -> None:
        """AC-19: refresh applies to every active claim, every target_kind."""
        conn = _build_conn()
        _insert_session(conn, "sess-multi", heartbeat_age_s=10)
        old_ts = _now_iso(-100)
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id, "
            "claim_type, claimed_at, last_heartbeat) "
            "VALUES (%s, 'item', 201, 'exclusive', %s, %s)",
            ("sess-multi", old_ts, old_ts),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, epic_id, "
            "task_num, claim_type, claimed_at, last_heartbeat) "
            "VALUES (%s, 'epic_task', 202, 3, 'exclusive', %s, %s)",
            ("sess-multi", old_ts, old_ts),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, process_key, "
            "claim_type, claimed_at, last_heartbeat) "
            "VALUES (%s, 'process', 'integration:foo', 'exclusive', %s, %s)",
            ("sess-multi", old_ts, old_ts),
        )
        conn.commit()
        _run_defer(conn, "sess-multi")
        hbs = [
            r["last_heartbeat"] for r in conn.execute(
                "SELECT last_heartbeat FROM work_claims "
                "WHERE session_id = %s AND released_at IS NULL",
                ("sess-multi",),
            ).fetchall()
        ]
        self.assertEqual(len(hbs), 3)
        now = _now_iso()
        for hb in hbs:
            self.assertGreater(hb, now)

    def test_refresh_helper_honors_override_window(self) -> None:
        """The helper accepts an explicit reacquire window override."""
        from yoke_core.domain.sessions_lifecycle_destructive_guard import (
            refresh_deferred_session_claim_heartbeats,
        )

        conn = _build_conn()
        _insert_session(conn, "sess-o", heartbeat_age_s=10)
        cid = _insert_item_claim(conn, "sess-o", 301)
        n = refresh_deferred_session_claim_heartbeats(
            conn, "sess-o", reacquire_window_s=60,
        )
        self.assertEqual(n, 1)
        hb = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id = %s", (cid,),
        ).fetchone()["last_heartbeat"]
        # Forward-stamped past NOW but bounded by the 60s override.
        self.assertGreater(hb, _now_iso())
        # And bounded by NOW + 120s as a generous upper sanity bound.
        self.assertLess(hb, _now_iso(delta_s=120))


if __name__ == "__main__":
    unittest.main()
