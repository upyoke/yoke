"""Polling reads avoid historical rows after the permanent index entry."""

from pathlib import Path
import sqlite3

import pytest

from yoke_core.domain.migration_history import load_migration_module


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_polling_indexes_replay_and_serve_selective_reads(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    for statement in (
        "CREATE TEMP TABLE items (id INTEGER, project_id INTEGER)",
        "CREATE TEMP TABLE epic_tasks (epic_id INTEGER, task_num INTEGER, item_worktree_id INTEGER)",
        "CREATE TEMP TABLE harness_sessions (session_id TEXT, actor_id INTEGER, machine_id TEXT)",
        "CREATE TEMP TABLE shepherd_verdicts (id INTEGER, public_ref TEXT, created_at TIMESTAMPTZ)",
        "CREATE TEMP TABLE deployment_runs (id TEXT, project_id INTEGER, created_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, target_environment_id INTEGER DEFAULT 1, status TEXT DEFAULT 'succeeded', driver_attachment TEXT)",
        "CREATE TEMP TABLE qa_requirements (id INTEGER, item_id INTEGER, epic_id INTEGER, deployment_member_item_id INTEGER)",
        "CREATE INDEX qa_item ON qa_requirements(item_id)",
        "CREATE INDEX qa_epic ON qa_requirements(epic_id)",
        "CREATE TEMP TABLE session_launch_attempts (batch_id TEXT, started_at TIMESTAMPTZ, relay_id TEXT, completed_at TIMESTAMPTZ)",
        "CREATE TEMP TABLE qa_plan_executions (id TEXT, deployment_run_id TEXT, state TEXT, created_at TIMESTAMPTZ)",
        "CREATE TEMP TABLE item_worktrees (id INTEGER, item_id INTEGER, released_at TIMESTAMPTZ, path TEXT, branch TEXT)",
        "INSERT INTO item_worktrees SELECT n,n,CASE WHEN n=1 THEN NULL ELSE now() END, '/repo/.worktrees/'||n::text,'branch-'||n::text "
        "FROM generate_series(1,4000) n",
        "CREATE TEMP TABLE work_claims (id INTEGER, claimed_at TIMESTAMPTZ, released_at TIMESTAMPTZ)",
        "CREATE TEMP TABLE session_messages (message_id TEXT, sender_session_id TEXT, "
        "selector_snapshot TEXT, cancelled_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ)",
        "CREATE TEMP TABLE session_launches (launch_id TEXT, registered_session_id TEXT, "
        "native_session_id TEXT, created_at TIMESTAMPTZ, project_id INTEGER, result_code TEXT, completed_at TIMESTAMPTZ, item_id INTEGER, origin TEXT)",
        "CREATE INDEX registered_session ON session_launches(registered_session_id)",
        "INSERT INTO work_claims SELECT n,now(),CASE WHEN n=1 THEN NULL ELSE now() END "
        "FROM generate_series(1,12000) n",
        "INSERT INTO session_messages SELECT n::text,n::text, "
        "json_build_object('launch_id',n::text)::text,NULL,CASE WHEN n=1 THEN '2100-01-01'::timestamptz ELSE '2020-01-01'::timestamptz END,now() FROM generate_series(1,44000) n",
        "INSERT INTO session_launches SELECT n::text,n::text,n::text,now(),n,'abandoned_without_claim',now(),n,'steering' "
        "FROM generate_series(1,4000) n",
    ):
        if "generate_series" not in statement or backend == "postgres":
            conn.execute(statement)
    if backend == "sqlite":
        conn.executemany(
            "INSERT INTO work_claims VALUES (?, ?, ?)",
            ((n, "now", None if n == 1 else "now") for n in range(1, 12001)),
        )
        conn.executemany(
            "INSERT INTO item_worktrees VALUES (?, ?, ?, ?, ?)",
            (
                (
                    n,
                    n,
                    None if n == 1 else "now",
                    f"/repo/.worktrees/{n}",
                    f"branch-{n}",
                )
                for n in range(1, 4001)
            ),
        )
        conn.executemany(
            "INSERT INTO session_messages VALUES (?, ?, ?, NULL, ?, ?)",
            (
                (
                    str(n),
                    str(n),
                    '{"launch_id":"%s"}' % n,
                    "2100-01-01" if n == 1 else "2020-01-01",
                    "2020-01-01",
                )
                for n in range(1, 44001)
            ),
        )
        conn.executemany(
            "INSERT INTO session_launches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    str(n),
                    str(n),
                    str(n),
                    "now",
                    n,
                    "abandoned_without_claim",
                    "2100-01-01",
                    n,
                    "steering",
                )
                for n in range(1, 4001)
            ),
        )
    for n in range(1, 2001):
        slots = "%s,%s,%s,%s" if backend == "postgres" else "?,?,?,?"
        conn.execute(
            f"INSERT INTO session_launch_attempts VALUES ({slots})",
            (str(n), "2020-01-01", "relay", None if n == 1 else "2020-01-01"),
        )
        conn.execute(
            f"INSERT INTO qa_plan_executions VALUES ({slots})",
            (str(n), str(n), "active" if n == 1 else "completed", "2020-01-01"),
        )
    for n in range(1, 4001):
        slots = "%s,%s,%s,%s" if backend == "postgres" else "?,?,?,?"
        conn.execute(f"INSERT INTO qa_requirements VALUES ({slots})", (n, n, n, n))
        conn.execute(
            f"INSERT INTO deployment_runs (id,project_id,created_at,completed_at) VALUES ({slots})",
            (str(n), n, "2020-01-01", None),
        )
    for n in range(1, 2001):
        slots = "%s,%s,%s" if backend == "postgres" else "?,?,?"
        pair = "%s,%s" if backend == "postgres" else "?,?"
        conn.execute(f"INSERT INTO items VALUES ({pair})", (n, n))
        conn.execute(f"INSERT INTO epic_tasks VALUES ({slots})", (n, 1, n))
        conn.execute(
            f"INSERT INTO harness_sessions VALUES ({slots})", (str(n), n, "machine")
        )
        conn.execute(
            f"INSERT INTO shepherd_verdicts VALUES ({slots})", (n, str(n), "2020-01-01")
        )
    conn.execute(
        "INSERT INTO deployment_runs (id,project_id,created_at,status,driver_attachment) "
        "VALUES ('driver',0,'2020-01-01','created','{}')"
    )
    from yoke_core.domain import migrations

    path = Path(migrations.__file__).parent / "0107_session_polling_indexes.py"
    module = load_migration_module(path, path.stem)
    module.apply(conn)
    module.apply(conn)
    for table in (
        "work_claims",
        "session_messages",
        "session_launches",
        "item_worktrees",
        "session_launch_attempts",
        "qa_plan_executions",
        "qa_requirements",
        "deployment_runs",
        "harness_sessions",
        "shepherd_verdicts",
    ):
        conn.execute(f"ANALYZE {table}")
    queries = (
        ("SELECT id FROM items WHERE CAST(id AS TEXT)='1'", "idx_items_id_text"),
        (
            "SELECT id FROM item_worktrees WHERE branch='branch-1' OR path='/repo/.worktrees/1'",
            "idx_item_worktrees_branch_history",
        ),
        (
            "SELECT id FROM item_worktrees WHERE path='/repo/.worktrees/1'",
            "idx_item_worktrees_path_history",
        ),
        (
            "SELECT task_num FROM epic_tasks WHERE item_worktree_id=1",
            "idx_epic_tasks_worktree",
        ),
        (
            "SELECT id FROM deployment_runs WHERE driver_attachment IS NOT NULL "
            "AND driver_attachment<>'' AND status NOT IN ('cancelled','failed','succeeded')",
            "idx_deployment_runs_live_driver",
        ),
        (
            "SELECT session_id FROM harness_sessions WHERE actor_id=1 AND machine_id IS NOT NULL",
            "idx_harness_sessions_actor_machine",
        ),
        (
            "SELECT id FROM shepherd_verdicts WHERE public_ref='1' ORDER BY created_at DESC,id DESC",
            "idx_shepherd_verdicts_ref_created",
        ),
        (
            "SELECT id FROM qa_plan_executions WHERE state='active' ORDER BY created_at,id",
            "idx_qa_plan_executions_state_created",
        ),
        (
            "SELECT id FROM deployment_runs WHERE project_id=1 AND target_environment_id=1 AND status='succeeded' ORDER BY completed_at DESC NULLS LAST,id DESC",
            "idx_deployment_runs_project_environment_status",
        ),
        (
            "SELECT id FROM qa_requirements WHERE item_id=1 OR epic_id=1 OR deployment_member_item_id=1",
            "idx_qa_requirements_member",
        ),
        (
            "SELECT id FROM deployment_runs WHERE project_id=1 AND COALESCE(completed_at,created_at)>'2000-01-01' ORDER BY COALESCE(completed_at,created_at) DESC LIMIT 1",
            "idx_deployment_runs_project_activity",
        ),
        (
            "SELECT launch_id FROM session_launches WHERE project_id=1 AND item_id=1 AND origin='steering' ORDER BY created_at DESC,launch_id DESC LIMIT 1",
            "idx_session_launches_project_item_origin",
        ),
        (
            "SELECT launch_id FROM session_launches WHERE project_id=1 "
            "AND result_code='abandoned_without_claim' AND completed_at>'2000-01-01' "
            "ORDER BY completed_at DESC,launch_id",
            "idx_session_launches_project_result_completed",
        ),
        (
            "SELECT DISTINCT relay_id,batch_id FROM session_launch_attempts "
            "WHERE completed_at IS NULL AND started_at<='2025-01-01'",
            "idx_session_launch_attempts_open_batch",
        ),
        (
            "SELECT id FROM qa_plan_executions WHERE deployment_run_id='1' "
            "AND state='active' ORDER BY created_at DESC,id DESC",
            "idx_qa_plan_executions_run_state",
        ),
        (
            "SELECT message_id FROM session_messages WHERE cancelled_at IS NULL "
            "AND expires_at>'2099-01-01'",
            "idx_session_messages_uncancelled_expiry",
        ),
        (
            "SELECT item_id,id FROM item_worktrees WHERE released_at IS NULL",
            "idx_item_worktrees_unreleased",
        ),
        (
            "SELECT id FROM work_claims WHERE released_at IS NULL ORDER BY claimed_at,id",
            "idx_work_claims_active_order",
        ),
        (
            "SELECT 1 FROM session_messages WHERE sender_session_id='1' LIMIT 1",
            "idx_session_messages_sender_session",
        ),
        (
            "SELECT message_id FROM session_messages WHERE cancelled_at IS NULL "
            "AND (NULLIF(selector_snapshot,'')::jsonb #>> '{launch_id}')='1'",
            "idx_session_messages_live_launch",
        ),
        (
            "SELECT launch_id FROM session_launches WHERE registered_session_id='1' "
            "OR native_session_id='1' ORDER BY created_at DESC LIMIT 1",
            "idx_session_launches_native_session",
        ),
    )
    for query, index in queries:
        if backend == "sqlite":
            query = query.replace(
                "NULLIF(selector_snapshot,'')::jsonb #>> '{launch_id}'",
                "json_extract(selector_snapshot, '$.launch_id')",
            )
        explain = "EXPLAIN " if backend == "postgres" else "EXPLAIN QUERY PLAN "
        plan = "\n".join(str(row[-1]) for row in conn.execute(explain + query))
        assert index in plan, plan
        assert "Seq Scan" not in plan, plan
        assert len(conn.execute(query).fetchall()) == 1
    if backend == "sqlite":
        conn.close()


def test_recorded_repo_roots_use_covering_index(test_db):
    from yoke_core.domain.lint_session_cwd_path_authority import recorded_repo_roots

    test_db.execute(
        "CREATE TEMP TABLE item_worktrees (item_id INTEGER,id INTEGER, "
        "released_at TIMESTAMPTZ, path TEXT, branch TEXT)"
    )
    test_db.execute(
        "CREATE TEMP TABLE work_claims (id INTEGER, claimed_at TIMESTAMPTZ, released_at TIMESTAMPTZ)"
    )
    test_db.execute(
        "CREATE TEMP TABLE session_messages (message_id TEXT, sender_session_id TEXT, selector_snapshot TEXT, cancelled_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ)"
    )
    test_db.execute(
        "CREATE TEMP TABLE session_launches (native_session_id TEXT, project_id INTEGER, result_code TEXT, completed_at TIMESTAMPTZ, launch_id TEXT, item_id INTEGER, origin TEXT, created_at TIMESTAMPTZ)"
    )
    test_db.execute(
        "INSERT INTO item_worktrees SELECT n,n,now(), '/repo/.worktrees/'||n,'branch-'||n "
        "FROM generate_series(1,4000) n"
    )
    from yoke_core.domain import migrations

    path = Path(migrations.__file__).parent / "0107_session_polling_indexes.py"
    load_migration_module(path, path.stem).apply(test_db)
    test_db.execute("ANALYZE item_worktrees")
    query = (
        "SELECT DISTINCT COALESCE(NULLIF(substring(btrim(path) FROM "
        "'^(.*)/[.]worktrees(?:/.*)?$'), ''), '/') AS repo_root "
        "FROM item_worktrees WHERE btrim(path) ~ '^.*/[.]worktrees(?:/.*)?$' "
        "ORDER BY repo_root"
    )
    plan = "\n".join(row[0] for row in test_db.execute("EXPLAIN " + query))
    assert "idx_item_worktrees_recorded_root" in plan, plan
    assert "Seq Scan" not in plan, plan
    assert recorded_repo_roots(test_db) == ["/repo"]
