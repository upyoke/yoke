"""Recipient work scales with addressed sessions, preserving anchor semantics."""

import pytest

from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)
from yoke_core.domain.session_automatic_reclaim import reclaim_facts
from yoke_core.domain.session_message_selectors import resolve_recipients


class ObservedCursor:
    def __init__(self, cursor, reads, sql):
        self.cursor, self.reads, self.sql = cursor, reads, sql

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def fetchall(self):
        rows = self.cursor.fetchall()
        self.reads.append((self.sql, len(rows)))
        return rows


class ObservedConnection:
    def __init__(self, conn):
        self._inner, self.reads = conn, []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def execute(self, sql, *args):
        cursor = self._inner.execute(sql, *args)
        if "FROM harness_sessions" in sql:
            return ObservedCursor(cursor, self.reads, sql)
        return cursor


def _with_history(count=8000):
    conn = message_connection()
    conn.executemany(
        "INSERT INTO harness_sessions (session_id,project_id,ended_at) VALUES (?,2,?)",
        [(f"historical-{i}", NOW.isoformat()) for i in range(count)],
    )
    return ObservedConnection(conn)


@pytest.mark.parametrize(
    "anchors,expected",
    [
        ({"session_ids": ["s1"]}, {"s1"}),
        ({"public_refs": ["ALP-1"]}, {"s1"}),
        ({"epic_tasks": ["ALP-1:1"]}, {"s2"}),
        ({"process_keys": ["build-beta"]}, {"s3"}),
        ({"projects": ["alpha"]}, {"s1", "s2", "s4"}),
        ({"universe": True}, {"s1", "s2", "s3", "s4"}),
        ({"session_ids": ["s1"], "process_keys": ["build-beta"]}, {"s1", "s3"}),
    ],
)
def test_anchor_hydration_ignores_unrelated_history(anchors, expected):
    conn = _with_history()
    recipients = resolve_recipients(conn, selector(**anchors), now=NOW)
    assert {row.session_id for row in recipients} == expected
    assert all(count <= len(expected) for _, count in conn.reads)
    assert not any("SELECT *" in sql for sql, _ in conn.reads)
    # One thin population read when needed, and one complete facts read.
    assert len(conn.reads) <= 2


def test_explicit_ended_anchor_survives_active_population_default():
    conn = _with_history()
    recipients = resolve_recipients(
        conn, selector(session_ids=["historical-0"], projects=["alpha"]), now=NOW
    )
    assert {row.session_id for row in recipients} == {"s1", "s2", "s4", "historical-0"}
    assert max(count for _, count in conn.reads) == 4


def test_partial_reclaim_input_refreshes_only_required_fields():
    conn = _with_history()
    row = reclaim_facts(conn, [{"session_id": "s1", "last_heartbeat": None}])[0]
    assert row["last_heartbeat"] is not None
    assert conn.reads[0][1] == 1
    assert "SELECT *" not in conn.reads[0][0]
    assert "workspace" not in conn.reads[0][0]


def test_deliberately_broad_ended_population_is_not_truncated():
    conn = _with_history(12)
    recipients = resolve_recipients(
        conn, selector(projects=["beta"], liveness=["ended"]), now=NOW
    )
    assert {row.session_id for row in recipients} == {
        f"historical-{i}" for i in range(12)
    }


def test_complete_input_still_rechecks_current_work_claims():
    conn = _with_history(0)
    rows = conn.execute(
        "SELECT * FROM harness_sessions WHERE session_id='s1'"
    ).fetchall()
    conn.reads.clear()
    conn.execute(
        "UPDATE work_claims SET released_at=? WHERE session_id='s1'", (NOW.isoformat(),)
    )
    row = reclaim_facts(conn, rows, session_facts_complete=True)[0]
    assert row["holds_work_claim"] is False
    assert conn.reads == []
