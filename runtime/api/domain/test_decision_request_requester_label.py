"""Question labels reflect current seats, locks and work without per-row reads."""

import json
from unittest.mock import Mock

from yoke_core.domain import decision_request_requester_label as labels


def add_holdings_schema(conn):
    conn.executescript("""
        ALTER TABLE harness_sessions ADD COLUMN machine_id TEXT;
        CREATE TABLE session_relays (machine_id TEXT, hostname TEXT, last_seen_at TEXT);
        ALTER TABLE work_claims ADD COLUMN claimed_at TEXT DEFAULT 'now';
        ALTER TABLE work_claims ADD COLUMN reason TEXT;
        CREATE TABLE epic_tasks (epic_id INTEGER, task_num INTEGER, item_worktree_id INTEGER);
        CREATE TABLE item_worktrees (
            id INTEGER, item_id INTEGER, state TEXT, lane_role TEXT
        );
    """)


def test_labels_current_holdings_and_harness_machine(monkeypatch):
    from runtime.api.domain.decision_request_test_support import decision_request_connection

    with decision_request_connection() as conn:
        conn.executescript("""
            CREATE TABLE harness_sessions (
                session_id TEXT, actor_id INTEGER, executor TEXT, machine_id TEXT
            );
            CREATE TABLE session_relays (machine_id TEXT, hostname TEXT, last_seen_at TEXT);
            CREATE TABLE work_claims (
                id INTEGER, session_id TEXT, target_kind TEXT, scope TEXT,
                claimed_at TEXT, released_at TEXT, reason TEXT
            );
            CREATE TABLE epic_tasks (epic_id INTEGER, task_num INTEGER, item_worktree_id INTEGER);
            CREATE TABLE item_worktrees (id INTEGER, item_id INTEGER, state TEXT, lane_role TEXT);
            UPDATE actors SET name='Morgan' WHERE id=1;
            INSERT INTO projects (id, slug) VALUES (11, 'platform');
            INSERT INTO harness_sessions VALUES ('asking', 1, 'claude-code', 'laptop');
            INSERT INTO harness_sessions VALUES ('idle', 1, 'cursor', 'laptop');
            INSERT INTO session_relays VALUES ('laptop', 'sample-mbp', 'now');
        """)
        scopes = [
            ('steering', {'project_id': 10}),
            ('steering', {'project_id': 11}),
            ('qa_admission', {'test_machine': 'browser'}),
            ('item', {'item_id': 12}),
            ('epic_task', {'epic_id': 13, 'task_num': 3}),
        ]
        for number, (kind, scope) in enumerate(scopes, 1):
            conn.execute(
                "INSERT INTO work_claims VALUES (?, 'asking', ?, ?, 'now', NULL, '')",
                (number, kind, json.dumps(scope)),
            )
        facts = Mock(return_value={
            12: {'public_ref': 'PLAT-345', 'item_title': 'Platform merge queue'},
            13: {'public_ref': 'PLAT-12', 'item_title': 'An epic'},
        })
        monkeypatch.setattr(labels, 'claimed_item_facts', facts)
        statements = []
        conn.set_trace_callback(statements.append)
        result = labels.requester_labels(conn, ['asking', 'idle', 'missing', 'asking'])
        assert result == {
            'asking': 'Morgan · steering seat for yoke and platform · QA_HOST:browser · '
            'PLAT-345 (Platform merge queue) and PLAT-12 task 3',
            'idle': 'Morgan · cursor on sample-mbp',
        }
        facts.assert_called_once_with(conn, [12, 13])
        assert len(statements) == 4
        conn.execute("UPDATE work_claims SET released_at='now' WHERE target_kind='item'")
        assert 'PLAT-345' not in labels.requester_labels(conn, ['asking'])['asking']
        conn.execute("UPDATE work_claims SET scope=? WHERE id=1", (
            json.dumps({'project_id': 10, 'document': 'CURRENT-PLAN'}),
        ))
        assert 'CURRENT-PLAN in yoke' in labels.requester_labels(conn, ['asking'])['asking']


def test_question_page_reads_labels_once(monkeypatch):
    from runtime.api.domain.test_decision_request_operator_question import conn as fixture, filing
    from yoke_core.domain.decision_request_question_filing import file_question
    from yoke_core.domain.decision_request_rows import request_rows

    # Reuse the question fixture without pytest fixture invocation.
    generator = fixture.__wrapped__()
    conn = next(generator)
    try:
        ids = [file_question(conn, **filing(
            requesting_session_id=session, subject_key=f'{session}:{key}',
        ))[0]['id'] for session, key in [('worker', 'one'), ('worker', 'two'), ('other', 'three')]]
        tracked = Mock(wraps=conn)
        actual = labels.requester_labels
        read = Mock(wraps=actual)
        monkeypatch.setattr(labels, 'requester_labels', read)
        rows = request_rows(tracked, ids)
        read.assert_called_once()
        assert set(read.call_args.args[1]) == {'worker', 'other'}
        sql = [call.args[0] for call in tracked.execute.call_args_list]
        assert sum('FROM harness_sessions s WHERE' in statement for statement in sql) == 1
        assert sum('FROM work_claims wc ' in statement for statement in sql) == 1
        assert sum('SELECT id, name FROM actors' in statement for statement in sql) == 1
        assert len(rows) == 3
        assert rows[ids[0]]['requesting_session_label'] == 'actor 1 · codex'
        assert rows[ids[2]]['requesting_session_label'] == 'actor 1 · cursor'
    finally:
        generator.close()
