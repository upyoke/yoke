"""Scoped withdrawal stays linear in notices, not messages times requirements."""

import sqlite3

import pytest

from yoke_core.domain import deployment_qa_manual_notice as notices


@pytest.mark.parametrize(
    "run_id,item_id,expected",
    [
        (None, None, {1, 2, 3, 4}),
        ("a", None, {1, 3, 4}),
        ("b", None, {2}),
        (None, 9, {1, 2, 3, 4, 5}),
        ("a", 9, {1, 3, 4, 5}),
    ],
)
def test_withdraw_uses_indexed_notice_prefix_and_exact_requirement_ids(
    monkeypatch,
    run_id,
    item_id,
    expected,
):
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        PRAGMA case_sensitive_like=ON;
        CREATE TABLE session_messages (
            message_id TEXT PRIMARY KEY,idempotency_key TEXT,cancelled_at TEXT);
        CREATE INDEX notice_prefix ON session_messages(idempotency_key);
        CREATE TABLE qa_requirements (id INTEGER PRIMARY KEY,
            deployment_run_id TEXT,deployment_member_item_id INTEGER,
            waived_at TEXT,superseded_at TEXT,retracted_at TEXT);
        CREATE TABLE qa_runs (qa_requirement_id INTEGER);
        CREATE INDEX requirement_runs ON qa_runs(qa_requirement_id);
    """)
    conn.executemany(
        "INSERT INTO qa_requirements VALUES (?,?,?,NULL,NULL,NULL)",
        ((i, "b" if i == 2 else "a", 9 if i == 5 else 8) for i in range(1, 20001)),
    )
    conn.execute("UPDATE qa_requirements SET waived_at='now' WHERE id IN (1,2)")
    conn.execute("UPDATE qa_requirements SET superseded_at='now' WHERE id=3")
    conn.execute("INSERT INTO qa_runs VALUES (4)")
    conn.executemany(
        "INSERT INTO session_messages VALUES (?,?,NULL)",
        [(str(i), f"deployment-qa-manual-wait:{i}:owner:digest") for i in range(1, 8)]
        + [(f"noise-{i}", f"unrelated:{i}") for i in range(20000)]
        + [("malformed", "deployment-qa-manual-wait:bad:key")],
    )
    conn.execute("UPDATE session_messages SET cancelled_at='then' WHERE message_id='7'")
    sql = []
    conn.set_trace_callback(sql.append)
    cancelled = []
    monkeypatch.setattr(
        notices,
        "cancel_messages",
        lambda _conn, **kw: cancelled.extend(kw["message_ids"]),
    )

    assert notices.withdraw_settled_manual_notices(
        conn,
        item_id=item_id,
        run_id=run_id,
        reason="settled",
        now=None,
    ) == len(expected)
    assert set(cancelled) == {str(i) for i in expected}
    reads = [query for query in sql if query.startswith("SELECT")]
    assert not any(
        "JOIN qa_requirements" in query or "CAST(q.id" in query for query in reads
    )
    notice_read = next(query for query in reads if "SELECT message_id," in query)
    requirement_read = next(query for query in reads if "SELECT q.id" in query)
    assert "SEARCH session_messages USING INDEX notice_prefix" in str(
        conn.execute("EXPLAIN QUERY PLAN " + notice_read).fetchall()
    )
    assert "SEARCH q USING INTEGER PRIMARY KEY" in str(
        conn.execute("EXPLAIN QUERY PLAN " + requirement_read).fetchall()
    )
    conn.close()
