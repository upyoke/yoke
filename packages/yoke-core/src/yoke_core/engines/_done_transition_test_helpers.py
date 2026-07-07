"""Shared module-level helpers and pytest fixtures for done_transition tests.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_done_transition.py and its split siblings.

The shared `dt_db` fixture creates a substantial DB schema (~70 lines)
that's needed by all done-transition tests; consolidating here avoids
3x duplication.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


@pytest.fixture
def dt_db(tmp_path, monkeypatch):
    """Create a minimal DB for done-transition engine tests."""
    db_path = tmp_path / "yoke.db"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    from yoke_core.domain import db_backend
    from runtime.api.fixtures import pg_testdb

    db_name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(db_name)
    prior_dsn = db_backend.resolve_pg_dsn()
    monkeypatch.setenv(
        db_backend.PG_DSN_ENV,
        pg_testdb.dsn_for_test_database(db_name),
    )
    try:
        apply_fixture_ddl(conn, """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            github_repo TEXT,
            public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
            default_branch TEXT DEFAULT 'main',
            created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT,
            type TEXT DEFAULT 'issue',
            status TEXT DEFAULT 'implementing',
            worktree TEXT,
            github_issue TEXT,
            project_id INTEGER NOT NULL,
            project_sequence INTEGER NOT NULL,
            deployment_flow TEXT,
            deploy_stage TEXT,
            deployed_to TEXT,
            merged_at TEXT,
            frozen INTEGER DEFAULT 0
        );
        CREATE TABLE epic_tasks (
            epic_id TEXT,
            task_num INTEGER,
            status TEXT,
            github_issue TEXT,
            PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE deployment_runs (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            status TEXT,
            current_stage TEXT,
            created_at TEXT
        );
        CREATE TABLE deployment_run_items (
            run_id TEXT,
            item_id INTEGER,
            PRIMARY KEY (run_id, item_id)
        );
        CREATE TABLE deployment_run_qa (
            run_id TEXT,
            check_name TEXT,
            blocking INTEGER,
            status TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            event_name TEXT,
            event_type TEXT,
            source_type TEXT,
            created_at TEXT,
            envelope TEXT
        );
        CREATE TABLE qa_requirements (
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            qa_kind TEXT,
            requirement_source TEXT
        );
        CREATE TABLE qa_runs (
            id INTEGER PRIMARY KEY,
            qa_requirement_id INTEGER,
            verdict TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            item_id INTEGER,
            epic_id INTEGER,
            task_num INTEGER,
            process_key TEXT,
            conflict_group TEXT,
            claim_type TEXT,
            claimed_at TEXT,
            last_heartbeat TEXT,
            released_at TEXT,
            release_reason TEXT
        );
        CREATE TABLE ephemeral_environments (
            id INTEGER PRIMARY KEY,
            item TEXT,
            status TEXT,
            stopped_at TEXT
        );
        CREATE TABLE release_entries (
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            category TEXT,
            title TEXT,
            version TEXT,
            project_id INTEGER NOT NULL,
            created_at TEXT,
            UNIQUE(item_id, version, project_id)
        );
        CREATE TABLE shepherd_verdicts (
            id INTEGER PRIMARY KEY,
            item TEXT NOT NULL,
            transition TEXT NOT NULL,
            worker TEXT NOT NULL,
            verdict TEXT NOT NULL,
            caveats TEXT,
            attempt INTEGER DEFAULT 1,
            created_at TEXT
        );
        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target_env TEXT
        );
        """)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, github_repo, public_item_prefix, "
            "default_branch, created_at) "
            "VALUES "
            "(1, 'yoke', 'Yoke', 'org/yoke', "
            "'YOK', 'main', '2026-01-01T00:00:00Z'), "
            "(2, 'buzz', 'Buzz', 'org/buzz', "
            "'BUZ', 'main', '2026-01-01T00:00:00Z')"
        )
        conn.commit()

        monkeypatch.setenv("YOKE_SCRIPTS_DIR", str(scripts_dir))
        yield db_path, scripts_dir
    finally:
        conn.close()
        monkeypatch.setenv(db_backend.PG_DSN_ENV, prior_dsn)
        pg_testdb.drop_test_database(db_name)


def connect_dt_db(db_path):
    """Connect to the active done-transition test database."""
    from runtime.api.fixtures.file_test_db import connect_test_db

    return connect_test_db(str(db_path))


def _project_id(project: str | int | None) -> int:
    if project is None:
        return 1
    if isinstance(project, int) or str(project).isdigit():
        return int(project)
    return 1 if str(project) == "yoke" else 2


def _insert_item(db_path, item_id, **kwargs):
    """Insert a test item with defaults."""
    project = kwargs.pop("project", "yoke")
    defaults = {
        "title": f"Test item {item_id}",
        "type": "issue",
        "status": "implementing",
        "worktree": f"YOK-{item_id}",
        "project_id": _project_id(project),
        "project_sequence": item_id,
    }
    defaults.update(kwargs)
    cols = ", ".join(["id"] + list(defaults.keys()))
    vals = [item_id] + list(defaults.values())
    conn = connect_dt_db(db_path)
    from yoke_core.domain import db_backend
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join([p] * (1 + len(defaults)))
    conn.execute(f"INSERT INTO items ({cols}) VALUES ({placeholders})", vals)
    conn.commit()
    conn.close()
