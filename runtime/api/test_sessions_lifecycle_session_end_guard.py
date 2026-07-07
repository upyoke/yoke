"""Coverage for the claim-and-chain destructive SessionEnd guard.

Pairs with ``sessions_lifecycle_destructive_guard.evaluate_destructive_end``
and the ``end_session(release_claims=True)`` branch in
``sessions_render_end``.

Chainable budget remaining defers the destructive path.
Chain-override-authorized waives the defer.
No chain pending releases claims normally.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from runtime.api.fixtures import pg_testdb
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements
from yoke_core.domain.sessions_lifecycle_destructive_guard import (
    evaluate_destructive_end,
)


_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    execution_lane TEXT NOT NULL DEFAULT 'primary',
    capabilities TEXT,
    workspace TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'wait',
    offered_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    ended_at TEXT,
    offer_envelope TEXT,
    actor_id INTEGER
);
"""

_CREATE_WORK_CLAIMS = """
CREATE TABLE IF NOT EXISTS work_claims (
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
"""

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    event_name TEXT NOT NULL,
    event_kind TEXT,
    event_type TEXT,
    source_type TEXT,
    session_id TEXT,
    project_id INTEGER,
    item_id TEXT,
    task_num INTEGER,
    context TEXT,
    outcome TEXT,
    severity TEXT,
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
    apply_ddl_statements(conn, _CREATE_SESSIONS, _CREATE_WORK_CLAIMS, _CREATE_EVENTS)
    conn.commit()
    return conn


def _insert_session(
    conn,
    session_id: str,
    *,
    chainable: bool = False,
    chain_step: int = 1,
    max_chain_steps: int = 3,
) -> None:
    envelope = {}
    if chainable:
        envelope = {
            "chain_checkpoint": {
                "chainable": True,
                "step": chain_step,
                "max_chain_steps": max_chain_steps,
                "action": "charge",
                "handler_outcome": "completed",
            },
        }
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, offered_at, "
        " last_heartbeat, ended_at, offer_envelope) "
        "VALUES (%s, 'claude-code', 'anthropic', 'm', '/tmp', %s, %s, NULL, %s)",
        (
            session_id,
            _now_iso(),
            _now_iso(),
            json.dumps(envelope),
        ),
    )
    conn.commit()


def _insert_active_claim(
    conn,
    session_id: str,
    item_id: int,
) -> int:
    ts = _now_iso()
    cursor = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, 'item', %s, 'exclusive', %s, %s) RETURNING id",
        (session_id, item_id, ts, ts),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.commit()
    return int(row[0])


class TestEvaluateDestructiveEnd(unittest.TestCase):
    def test_chain_pending_defers(self) -> None:
        conn = _build_conn()
        _insert_session(conn, "sess-chain", chainable=True)
        decision = evaluate_destructive_end(conn, "sess-chain")
        self.assertTrue(decision.defer)
        self.assertEqual(decision.reason, "chain_pending")

    def test_no_chain_falls_through(self) -> None:
        conn = _build_conn()
        _insert_session(conn, "sess-perm", chainable=False)
        decision = evaluate_destructive_end(conn, "sess-perm")
        self.assertFalse(decision.defer)
        self.assertEqual(decision.reason, "permanent")

    def test_chain_override_authorized_skips_chain_pending_defer(self) -> None:
        conn = _build_conn()
        _insert_session(conn, "sess-override", chainable=True)
        decision = evaluate_destructive_end(
            conn, "sess-override", chain_override_authorized=True,
        )
        self.assertFalse(decision.defer)
        self.assertEqual(decision.reason, "permanent")
        self.assertTrue(decision.evidence.chain_override_authorized)


class TestEndSessionReleaseClaimsBranch(unittest.TestCase):
    def test_chain_pending_does_not_release(self) -> None:
        from yoke_core.domain.sessions_lifecycle_destructive_guard import (
            handle_release_claims_branch,
        )

        conn = _build_conn()
        _insert_session(conn, "sess-t", chainable=True)
        _insert_active_claim(conn, "sess-t", 7)
        rows = conn.execute(
            "SELECT id, item_id, task_num FROM work_claims "
            "WHERE session_id = %s AND released_at IS NULL",
            ("sess-t",),
        ).fetchall()
        with mock.patch(
            "yoke_core.domain.scheduler_events.emit_harness_session_end_deferred",
        ) as deferred_emit, mock.patch(
            "yoke_core.domain.sessions_lifecycle_release.release_all_claims",
        ) as release:
            deferred, evidence = handle_release_claims_branch(
                conn, "sess-t", force=True, active_claim_rows=rows,
            )
        self.assertTrue(deferred)
        deferred_emit.assert_called_once()
        release.assert_not_called()
        self.assertTrue(evidence["chain_budget_remaining"])

    def test_permanent_signal_releases_and_returns_evidence(self) -> None:
        from yoke_core.domain.sessions_lifecycle_destructive_guard import (
            handle_release_claims_branch,
        )

        conn = _build_conn()
        _insert_session(conn, "sess-p", chainable=False)
        _insert_active_claim(conn, "sess-p", 8)
        rows = conn.execute(
            "SELECT id, item_id, task_num FROM work_claims "
            "WHERE session_id = %s AND released_at IS NULL",
            ("sess-p",),
        ).fetchall()
        with mock.patch(
            "yoke_core.domain.scheduler_events.emit_harness_session_end_deferred",
        ) as deferred_emit, mock.patch(
            "yoke_core.domain.sessions_lifecycle_release.release_all_claims",
            return_value=1,
        ) as release, mock.patch(
            "yoke_core.domain.sessions_analytics._emit_session_event",
        ):
            deferred, evidence = handle_release_claims_branch(
                conn, "sess-p", force=True, active_claim_rows=rows,
            )
        self.assertFalse(deferred)
        deferred_emit.assert_not_called()
        release.assert_called_once()
        self.assertFalse(evidence["chain_budget_remaining"])


if __name__ == "__main__":
    unittest.main()
