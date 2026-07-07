"""Coverage for :mod:`claims_work_release_session_scoped`.

AC-1 releases every active claim for the caller (emits one WorkReleased
per claim with intent=agent_handoff_session_scoped). AC-2 leaves
already-released rows untouched. AC-3 strict same-session filter.
AC-17 reuses release_session_claims (no duplicated loop). AC-20 strict
filter releases only the caller's own claims and never another
session's. Idempotency + zero-effect also covered.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain import claims_work_release_session_scoped as mod


_DDL = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY, executor TEXT NOT NULL, provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '', execution_lane TEXT NOT NULL DEFAULT 'primary',
    workspace TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'wait',
    offered_at TEXT NOT NULL, last_heartbeat TEXT NOT NULL,
    ended_at TEXT,
    current_item_id TEXT, current_item_set_at TEXT,
    recent_item_id TEXT, recent_item_status TEXT,
    recent_item_recorded_at TEXT, actor_id INTEGER
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, target_kind TEXT NOT NULL,
    item_id INTEGER, epic_id INTEGER, task_num INTEGER, process_key TEXT,
    conflict_group TEXT, claim_type TEXT NOT NULL DEFAULT 'exclusive',
    claimed_at TEXT NOT NULL, last_heartbeat TEXT NOT NULL, released_at TEXT,
    release_reason TEXT CHECK(release_reason IS NULL OR release_reason IN
        ('completed','released','reclaimed','handed_off','expired','session_ended'))
);
CREATE TABLE items (id INTEGER PRIMARY KEY, status TEXT);
CREATE TABLE events (
    id INTEGER PRIMARY KEY, event_name TEXT NOT NULL, session_id TEXT,
    item_id TEXT, task_num INTEGER, context TEXT,
    created_at TEXT NOT NULL DEFAULT (now()::text)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _build_conn():
    """Build a disposable-Postgres session/work-claim double."""
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(conn, _DDL)
    return conn


def _insert_session(conn, session_id):
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, workspace, "
        "offered_at, last_heartbeat) "
        "VALUES (%s, 'claude-code', 'anthropic', 'm', '/tmp', %s, %s)",
        (session_id, _now(), _now()),
    )
    conn.commit()


def _insert_item_claim(conn, session_id, item_id, *, released=False):
    conn.execute(
        "INSERT INTO items (id, status) VALUES (%s, 'implementing') "
        "ON CONFLICT (id) DO NOTHING",
        (item_id,),
    )
    cur = conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type, "
        "claimed_at, last_heartbeat, released_at, release_reason) "
        "VALUES (%s, 'item', %s, 'exclusive', %s, %s, %s, %s) RETURNING id",
        (session_id, item_id, _now(), _now(),
         _now() if released else None, "released" if released else None),
    )
    claim_id = int(cur.fetchone()[0])
    conn.commit()
    return claim_id


class _ConnCM:
    def __init__(self, conn): self._conn = conn
    def __enter__(self): return self._conn
    def __exit__(self, *args): return None


def _patches(conn):
    return (
        mock.patch(
            "yoke_core.domain.claims_work_release_session_scoped.db_helpers.connect",
            side_effect=lambda: _ConnCM(conn),
        ),
        mock.patch("yoke_core.domain.sessions_lifecycle_release._sa._emit_session_event"),
        mock.patch("yoke_core.domain.sessions_render_end_claim_release._sa._emit_session_event"),
    )


class TestReleaseAllClaimsForSession(unittest.TestCase):
    def test_releases_every_active_claim_for_caller(self):
        conn = _build_conn()
        _insert_session(conn, "sess-A")
        cid1 = _insert_item_claim(conn, "sess-A", 101)
        cid2 = _insert_item_claim(conn, "sess-A", 102)
        p1, p2, p3 = _patches(conn)
        with p1, p2, p3:
            result = mod.release_all_claims_for_session("sess-A")
        self.assertEqual(result["released_count"], 2)
        self.assertEqual({e["claim_id"] for e in result["released_claims"]}, {cid1, cid2})
        rows = conn.execute(
            "SELECT release_reason FROM work_claims "
            "WHERE session_id='sess-A' AND released_at IS NOT NULL"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["release_reason"], "handed_off")

    def test_released_claims_not_resurrected(self):
        conn = _build_conn()
        _insert_session(conn, "sess-B")
        old_cid = _insert_item_claim(conn, "sess-B", 200, released=True)
        active_cid = _insert_item_claim(conn, "sess-B", 201)
        p1, p2, p3 = _patches(conn)
        with p1, p2, p3:
            result = mod.release_all_claims_for_session("sess-B")
        self.assertEqual(result["released_count"], 1)
        self.assertEqual(result["released_claims"][0]["claim_id"], active_cid)
        row = conn.execute(
            "SELECT release_reason FROM work_claims WHERE id=%s", (old_cid,)
        ).fetchone()
        self.assertEqual(row["release_reason"], "released")

    def test_other_sessions_claims_untouched(self):
        conn = _build_conn()
        _insert_session(conn, "sess-mine")
        _insert_session(conn, "sess-theirs")
        mine = _insert_item_claim(conn, "sess-mine", 300)
        theirs = _insert_item_claim(conn, "sess-theirs", 301)
        p1, p2, p3 = _patches(conn)
        with p1, p2, p3:
            result = mod.release_all_claims_for_session("sess-mine")
        self.assertEqual(result["released_count"], 1)
        self.assertEqual(result["released_claims"][0]["claim_id"], mine)
        row = conn.execute(
            "SELECT released_at FROM work_claims WHERE id=%s", (theirs,)
        ).fetchone()
        self.assertIsNone(row["released_at"])

    def test_strict_same_session_filter(self):
        # AC-20 — release_all_claims_for_session releases only the
        # caller's own claims. Direct same-session match is the only
        # criterion; another session's claim is left untouched even when
        # the two sessions share an unrelated relationship.
        conn = _build_conn()
        _insert_session(conn, "sess-other")
        _insert_session(conn, "sess-mine")
        other_cid = _insert_item_claim(conn, "sess-other", 400)
        mine_cid = _insert_item_claim(conn, "sess-mine", 401)
        p1, p2, p3 = _patches(conn)
        with p1, p2, p3:
            result = mod.release_all_claims_for_session("sess-mine")
        self.assertEqual(result["released_count"], 1)
        self.assertEqual(result["released_claims"][0]["claim_id"], mine_cid)
        row = conn.execute(
            "SELECT released_at FROM work_claims WHERE id=%s", (other_cid,)
        ).fetchone()
        self.assertIsNone(row["released_at"])

    def test_idempotent_second_call_no_op(self):
        conn = _build_conn()
        _insert_session(conn, "sess-idem")
        _insert_item_claim(conn, "sess-idem", 500)
        p1, p2, p3 = _patches(conn)
        with p1, p2, p3:
            first = mod.release_all_claims_for_session("sess-idem")
            second = mod.release_all_claims_for_session("sess-idem")
        self.assertEqual(first["released_count"], 1)
        self.assertEqual(second["released_count"], 0)
        self.assertEqual(second["released_claims"], [])

    def test_zero_effect_when_no_active_claims(self):
        conn = _build_conn()
        _insert_session(conn, "sess-empty")
        p1, p2, p3 = _patches(conn)
        with p1, p2, p3:
            result = mod.release_all_claims_for_session("sess-empty")
        self.assertEqual(result, {"released_count": 0, "released_claims": []})

    def test_empty_session_id_returns_zero_effect(self):
        with mock.patch(
            "yoke_core.domain.claims_work_release_session_scoped.db_helpers.connect"
        ) as connect:
            result = mod.release_all_claims_for_session("")
        connect.assert_not_called()
        self.assertEqual(result, {"released_count": 0, "released_claims": []})

    def test_event_carries_agent_handoff_intent(self):
        # AC-1 — intent surfaces on per-claim WorkReleased + aggregate event.
        conn = _build_conn()
        _insert_session(conn, "sess-evt")
        _insert_item_claim(conn, "sess-evt", 600)
        captured = []

        def capture(name, **kwargs):
            captured.append((name, kwargs.get("context") or {}))

        with mock.patch(
            "yoke_core.domain.claims_work_release_session_scoped.db_helpers.connect",
            side_effect=lambda: _ConnCM(conn),
        ), mock.patch(
            "yoke_core.domain.sessions_lifecycle_release._sa._emit_session_event",
            side_effect=capture,
        ), mock.patch(
            "yoke_core.domain.sessions_render_end_claim_release._sa._emit_session_event",
            side_effect=capture,
        ):
            mod.release_all_claims_for_session("sess-evt")
        wr = [(n, c) for n, c in captured if n == "WorkReleased"]
        self.assertEqual(len(wr), 1)
        self.assertEqual(
            wr[0][1].get("release_reason_intent"), mod.AGENT_HANDOFF_RELEASE_REASON
        )
        agg = [(n, c) for n, c in captured if n == "HarnessSessionEndReleasedClaims"]
        self.assertEqual(len(agg), 1)
        self.assertEqual(agg[0][1].get("via"), "agent_handoff_session_scoped")
        self.assertEqual(agg[0][1].get("release_reason"), mod.AGENT_HANDOFF_RELEASE_REASON)

    def test_reuses_release_session_claims_no_duplicated_loop(self):
        # AC-17 — verify route through shared helper, not a re-implementation.
        conn = _build_conn()
        _insert_session(conn, "sess-reuse")
        _insert_item_claim(conn, "sess-reuse", 700)
        called_with = {}

        def fake_release(conn_arg, sid, *, active_claim_rows, release_reason, via):
            called_with.update({
                "sid": sid, "count": len(active_claim_rows),
                "reason": release_reason, "via": via,
            })
            return [{"claim_id": 999, "target_kind": "item", "item_id": 700}]

        with mock.patch(
            "yoke_core.domain.claims_work_release_session_scoped.db_helpers.connect",
            side_effect=lambda: _ConnCM(conn),
        ), mock.patch(
            "yoke_core.domain.claims_work_release_session_scoped.release_session_claims",
            side_effect=fake_release,
        ):
            result = mod.release_all_claims_for_session("sess-reuse")
        self.assertEqual(called_with["sid"], "sess-reuse")
        self.assertEqual(called_with["count"], 1)
        self.assertEqual(called_with["reason"], mod.AGENT_HANDOFF_RELEASE_REASON)
        self.assertEqual(called_with["via"], "agent_handoff_session_scoped")
        self.assertEqual(result["released_count"], 1)


if __name__ == "__main__":
    unittest.main()
