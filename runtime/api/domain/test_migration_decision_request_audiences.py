"""Historical deciders survive audience backfill without duplicate storage."""

import importlib

from runtime.api.domain.decision_request_test_support import decision_request_connection
from yoke_core.domain.audiences import member_matches

migration = importlib.import_module(
    "yoke_core.domain.migrations.0101_decision_request_audiences"
)


def _legacy(conn):
    conn.executescript("""
        CREATE TABLE decision_request_role_authorities(request_id INTEGER, scope_kind TEXT, scope_id INTEGER, role_name TEXT);
        CREATE TABLE decision_request_actor_authorities(request_id INTEGER, actor_id INTEGER);
    """)
    for request_id, status in enumerate(("pending", "resolved", "withdrawn"), 1):
        conn.execute(
            "INSERT INTO decision_requests(id, kind, subject_type, subject_key, project_id, status, created_at) VALUES (?, 'operator_question', 'session_question', ?, 10, ?, '2026-01-01T00:00:00Z')",
            (request_id, str(request_id), status),
        )
        conn.execute(
            "INSERT INTO decision_request_role_authorities VALUES (?, 'project', 10, 'owner')",
            (request_id,),
        )
        conn.execute(
            "INSERT INTO decision_request_role_authorities VALUES (?, 'org', 1, 'admin')",
            (request_id,),
        )
        conn.execute(
            "INSERT INTO decision_request_actor_authorities VALUES (?, 3)",
            (request_id,),
        )
    conn.commit()


def _old_deciders(conn, request_id):
    # The old live resolver's three membership joins, evaluated against the
    # historical tables before any audience is attached to the request.
    return {
        row[0]
        for row in conn.execute(
            """
        SELECT a.id FROM actors a WHERE a.kind='human' AND a.status='active' AND (
          EXISTS (SELECT 1 FROM decision_request_actor_authorities n WHERE n.request_id=? AND n.actor_id=a.id)
          OR EXISTS (SELECT 1 FROM decision_request_role_authorities r JOIN actor_project_roles ar ON ar.project_id=r.scope_id JOIN roles ro ON ro.id=ar.role_id WHERE r.request_id=? AND r.scope_kind='project' AND ro.name=r.role_name AND ar.actor_id=a.id)
          OR EXISTS (SELECT 1 FROM decision_request_role_authorities r JOIN actor_org_roles ar ON ar.org_id=r.scope_id JOIN roles ro ON ro.id=ar.role_id WHERE r.request_id=? AND r.scope_kind='org' AND ro.name=r.role_name AND ar.actor_id=a.id))
    """,
            (request_id, request_id, request_id),
        ).fetchall()
    }


def test_backfill_preserves_actual_deciders_history_and_rerun_counts():
    with decision_request_connection() as conn:
        _legacy(conn)
        before = {
            request_id: _old_deciders(conn, request_id) for request_id in (1, 2, 3)
        }
        rows_before = [
            tuple(row)
            for row in conn.execute(
                "SELECT id, kind, subject_type, subject_key, status, created_at FROM decision_requests"
            )
        ]
        assert all(value == {2, 3, 5} for value in before.values())
        migration.apply(conn)
        migration.invariants(conn)
        counts = tuple(
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("audiences", "audience_rules")
        )
        assert counts == (3, 9)
        for request_id, audience_id in conn.execute(
            "SELECT id, audience_id FROM decision_requests"
        ):
            assert {
                row["actor_id"] for row in member_matches(conn, audience_id)
            } == before[request_id]
        assert [
            tuple(row)
            for row in conn.execute(
                "SELECT id, kind, subject_type, subject_key, status, created_at FROM decision_requests"
            )
        ] == rows_before
        migration.apply(conn)
        migration.invariants(conn)
        assert (
            tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("audiences", "audience_rules")
            )
            == counts
        )
        conn.execute("INSERT INTO actor_project_roles VALUES (4, 10, 1, 'later')")
        assert {row["actor_id"] for row in member_matches(conn, 1)} == {2, 3, 4, 5}


def test_fresh_schema_never_recreates_retired_tables():
    from yoke_core.domain.decision_request_schema import create_decision_request_tables

    with decision_request_connection() as conn:
        migration.apply(conn)
        create_decision_request_tables(conn)
        migration.invariants(conn)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert (
            migration.ROLE_TABLE not in tables and migration.ACTOR_TABLE not in tables
        )


def test_migration_does_not_commit_callers_work():
    with decision_request_connection() as conn:
        _legacy(conn)
        conn.execute("BEGIN")
        migration.apply(conn)
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM audiences").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM decision_request_actor_authorities"
            ).fetchone()[0]
            == 3
        )
