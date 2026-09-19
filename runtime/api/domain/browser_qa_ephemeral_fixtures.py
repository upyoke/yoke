"""Ephemeral-deployment fixtures for browser QA tests.

The browser QA context a scenario reads is assembled server-side by
``qa.browser_context.get``; these stand in for it against a per-test
database, and for the ``ephemeral_environments`` rows it reads. Keeping
them together means the stand-in and the rows it reads stay one story —
when the handler's read grows a predicate, there is one place here that
has to grow with it.
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_core.domain import db_backend
from yoke_core.domain.browser_qa_deployment_identity import (
    resolve_run_pinned_source,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.schema_init_apply import execute_schema_script


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def ensure_ephemeral_table(db_path: str) -> None:
    """Create the ephemeral_environments table and its project row."""
    conn = connect_test_db(db_path)
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS ephemeral_environments (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            branch TEXT NOT NULL,
            item TEXT,
            workflow_run_id TEXT,
            github_ref TEXT,
            port_api INTEGER,
            port_web INTEGER,
            url TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT,
            stopped_at TEXT,
            health_check_url TEXT,
            deployed_sha TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, branch)
        );
    """)
    conn.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (100, 'testproj', 'Test Project', 'YOK', '2026-01-01T00:00:00Z') "
        "ON CONFLICT(id) DO NOTHING",
    )
    conn.commit()
    conn.close()


def seed_ephemeral_env(
    db_path: str,
    project: str,
    branch: str,
    deployed_sha: str = "",
    url: str = "",
) -> int:
    """Seed one recorded deployment; an empty url records none."""
    ensure_ephemeral_table(db_path)
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    cur = conn.execute(
        f"""
        INSERT INTO ephemeral_environments
            (project_id, branch, deployed_sha, url, status, created_at)
        VALUES ({p}, {p}, {p}, {p}, 'healthy', {p}) RETURNING id
        """,
        (100, branch, deployed_sha, url, "2026-01-01T00:00:00Z"),
    )
    env_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return env_id


def seed_deployment_run(
    db_path: str,
    run_id: str,
    *,
    project_id: int = 100,
    release_lineage: str = "",
    default_branch: str = "main",
) -> None:
    """Seed one deployment run pinned (or deliberately not pinned) to a commit.

    Only the two columns the browser-QA read needs are modelled here, without
    the flow and environment foreign keys a real run carries: what this suite
    is about is which commit the run names, not how runs are built.
    """
    ensure_ephemeral_table(db_path)
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS deployment_runs (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            flow TEXT NOT NULL,
            release_lineage TEXT,
            status TEXT NOT NULL DEFAULT 'created',
            created_at TEXT NOT NULL
        );
        ALTER TABLE projects
            ADD COLUMN IF NOT EXISTS default_branch TEXT DEFAULT 'main';
    """)
    conn.execute(
        f"UPDATE projects SET default_branch = {p} WHERE id = {p}",
        (default_branch, project_id),
    )
    conn.execute(
        f"""
        INSERT INTO deployment_runs
            (id, project_id, flow, release_lineage, status, created_at)
        VALUES ({p}, {p}, 'test-flow', {p}, 'running', {p})
        ON CONFLICT(id) DO NOTHING
        """,
        (run_id, project_id, release_lineage, "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()


def _fetch_context_from_test_db(
    project: str,
    requirement_id: int,
    *,
    db_path: str,
    item_id: int | None = None,
    deployment_run_id: str | None = None,
    expected_branch: str | None = None,
    actor: Any = None,
) -> Dict[str, Any]:
    """Direct-DB stand-in for browser_qa._fetch_browser_context.

    Mirrors the qa.browser_context.get handler's reads against the per-test
    DB — including its one-subject rule, so a deployment-run case reads
    through the same stand-in an item case does — without the dispatcher's
    identity/claim machinery.
    """
    subject_column = "item_id" if item_id is not None else "deployment_run_id"
    subject_value = item_id if item_id is not None else deployment_run_id
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    try:
        rows = conn.execute(
            "SELECT id, qa_kind, method_id, method_config, expected_outcome "
            "FROM qa_requirements "
            f"WHERE {subject_column} = {p} AND id = {p} "
            "AND method_id IN ('browser-check', 'browser-inspection') "
            "AND waived_at IS NULL",
            (subject_value, requirement_id),
        ).fetchall()
        requirements = [
            {
                "id": int(r[0]),
                "qa_kind": str(r[1]),
                "method_id": str(r[2]),
                "method_config": r[3],
                "expected_outcome": r[4],
            }
            for r in rows
        ]
        run_source = None
        if deployment_run_id is not None:
            # Mirrors the handler: a run case is judged against the commit
            # the run was pinned to deliver.
            run_source = resolve_run_pinned_source(conn, str(deployment_run_id))
        deployed_sha = None
        deployment_recorded = False
        ephemeral_url = None
        if expected_branch:
            env_rows = conn.execute(
                "SELECT e.deployed_sha FROM ephemeral_environments e "
                "JOIN projects pr ON e.project_id = pr.id "
                f"WHERE pr.slug = {p} AND e.branch = {p} "
                "ORDER BY e.id DESC LIMIT 1",
                (project, expected_branch),
            ).fetchall()
            if env_rows:
                deployment_recorded = True
                deployed_sha = env_rows[0][0] or None
            # Mirrors the handler's own second predicate: the newest row may
            # predate the URL write, so the recorded target is the newest row
            # that actually carries one.
            url_rows = conn.execute(
                "SELECT e.url FROM ephemeral_environments e "
                "JOIN projects pr ON e.project_id = pr.id "
                f"WHERE pr.slug = {p} AND e.branch = {p} "
                "AND e.url IS NOT NULL AND e.url <> '' "
                "ORDER BY e.id DESC LIMIT 1",
                (project, expected_branch),
            ).fetchall()
            if url_rows:
                ephemeral_url = str(url_rows[0][0])
    finally:
        conn.close()
    return {
        "item_id": item_id,
        "deployment_run_id": deployment_run_id,
        "requirements": requirements,
        "deployed_sha": deployed_sha,
        "deployment_recorded": deployment_recorded,
        "ephemeral_url": ephemeral_url,
        "run_source": run_source,
    }
