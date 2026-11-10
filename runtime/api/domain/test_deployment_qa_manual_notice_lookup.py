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


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_manual_notice_reads_exact_current_keys(monkeypatch, test_db, backend):
    from hashlib import sha256

    from yoke_core.domain.qa_plan_execution_store import marker

    conn = sqlite3.connect(":memory:") if backend == "sqlite" else test_db
    if backend == "sqlite":
        conn.row_factory = sqlite3.Row
    statements = [
        "CREATE TEMP TABLE qa_requirements (id INTEGER PRIMARY KEY, "
        "deployment_run_id TEXT, deployment_stage TEXT, "
        "deployment_member_item_id INTEGER, wake_evidence TEXT)",
        "CREATE TEMP TABLE session_messages (message_id TEXT PRIMARY KEY, "
        "idempotency_key TEXT, created_at TEXT, cancelled_at TEXT)",
        "CREATE TEMP TABLE session_message_recipients (message_id TEXT, "
        "session_id TEXT, state TEXT, wake_escalation TEXT)",
        "CREATE TEMP TABLE harness_sessions (session_id TEXT, ended_at TEXT)",
        "CREATE INDEX exact_notice_key ON session_messages(idempotency_key)",
    ]
    for statement in statements:
        conn.execute(statement)
    p = marker(conn)
    for requirement, run, stage, evidence in [
        (1, "a", "qa", "ready"),
        (2, "b", "qa", "carried"),
        (3, "a", "other", "other"),
        (4, "a", "qa", "changed"),
    ]:
        conn.execute(
            f"INSERT INTO qa_requirements VALUES ({','.join([p] * 5)})",
            (requirement, run, stage, 9, evidence),
        )
        digest = sha256(evidence.encode()).hexdigest()
        conn.execute(
            f"INSERT INTO session_messages VALUES ({p},{p},{p},NULL)",
            (
                str(requirement),
                f"{notices.MANUAL_WAIT_PREFIX}{requirement}:s:{digest}",
                "now",
            ),
        )
    conn.execute("UPDATE qa_requirements SET wake_evidence='new' WHERE id=4")
    conn.execute(
        f"INSERT INTO session_messages VALUES ({p},{p},{p},NULL)",
        ("old", f"{notices.MANUAL_WAIT_PREFIX}1:stale", "before"),
    )
    conn.execute(
        "INSERT INTO session_message_recipients VALUES ('1','s','acknowledged','')"
    )
    conn.execute("INSERT INTO harness_sessions VALUES ('s',NULL)")
    monkeypatch.setattr(notices, "_table_exists", lambda *_: True)
    from yoke_core.domain import deployment_qa_presentation_facts as facts
    from yoke_core.domain import deployment_qa_presentation_reads as reads

    monkeypatch.setattr(facts, "presented_run_ids", lambda *_: ("a", "b"))
    queries = []

    def read(_conn, _key, callback):
        if backend == "sqlite":
            conn.set_trace_callback(queries.append)
        return callback()

    monkeypatch.setattr(reads, "presentation_read", read)
    result = notices.manual_notice_rows(conn, run_id="a", stage_name="qa")
    assert result == [
        {
            "message_id": "1",
            "idempotency_key": "deployment-qa-stage-wait:a:qa:9:manual:1",
            "sent_at": "now",
            "session_id": "s",
            "state": "acknowledged",
            "escalation": "",
        }
    ]
    if backend == "sqlite":
        query = next(q for q in queries if "FROM session_messages m" in q)
        assert "LIKE" not in query
        assert "exact_notice_key" in str(
            [tuple(row) for row in conn.execute("EXPLAIN QUERY PLAN " + query)]
        )
        conn.close()
