"""Polling reads avoid historical rows after the permanent index entry."""

from pathlib import Path

from yoke_core.domain.migration_history import load_migration_module


def test_polling_indexes_replay_and_serve_selective_reads(test_db):
    conn = test_db
    for statement in (
        "CREATE TEMP TABLE item_worktrees (id INTEGER, item_id INTEGER, released_at TIMESTAMPTZ)",
        "INSERT INTO item_worktrees SELECT n,n,CASE WHEN n=1 THEN NULL ELSE now() END "
        "FROM generate_series(1,4000) n",
        "CREATE TEMP TABLE work_claims (id INTEGER, claimed_at TIMESTAMPTZ, released_at TIMESTAMPTZ)",
        "CREATE TEMP TABLE session_messages (message_id TEXT, sender_session_id TEXT, "
        "selector_snapshot TEXT, cancelled_at TIMESTAMPTZ)",
        "CREATE TEMP TABLE session_launches (launch_id TEXT, registered_session_id TEXT, "
        "native_session_id TEXT, created_at TIMESTAMPTZ)",
        "CREATE INDEX registered_session ON session_launches(registered_session_id)",
        "INSERT INTO work_claims SELECT n,now(),CASE WHEN n=1 THEN NULL ELSE now() END "
        "FROM generate_series(1,12000) n",
        "INSERT INTO session_messages SELECT n::text,n::text, "
        "json_build_object('launch_id',n::text)::text,NULL FROM generate_series(1,44000) n",
        "INSERT INTO session_launches SELECT n::text,n::text,n::text,now() "
        "FROM generate_series(1,4000) n",
    ):
        conn.execute(statement)
    from yoke_core.domain import migrations

    path = Path(migrations.__file__).parent / "0107_session_polling_indexes.py"
    module = load_migration_module(path, path.stem)
    module.apply(conn)
    module.apply(conn)
    for table in ("work_claims", "session_messages", "session_launches", "item_worktrees"):
        conn.execute(f"ANALYZE {table}")
    queries = (
        ("SELECT item_id,id FROM item_worktrees WHERE released_at IS NULL",
         "idx_item_worktrees_unreleased"),
        ("SELECT id FROM work_claims WHERE released_at IS NULL ORDER BY claimed_at,id",
         "idx_work_claims_active_order"),
        ("SELECT 1 FROM session_messages WHERE sender_session_id='1' LIMIT 1",
         "idx_session_messages_sender_session"),
        ("SELECT message_id FROM session_messages WHERE cancelled_at IS NULL "
         "AND (NULLIF(selector_snapshot,'')::jsonb #>> '{launch_id}')='1'",
         "idx_session_messages_live_launch"),
        ("SELECT launch_id FROM session_launches WHERE registered_session_id='1' "
         "OR native_session_id='1' ORDER BY created_at DESC LIMIT 1",
         "idx_session_launches_native_session"),
    )
    for query, index in queries:
        plan = "\n".join(str(row[0]) for row in conn.execute("EXPLAIN " + query))
        assert index in plan, plan
        assert "Seq Scan" not in plan, plan
        assert len(conn.execute(query).fetchall()) == 1
