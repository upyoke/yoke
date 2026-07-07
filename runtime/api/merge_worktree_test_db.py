"""Database helper functions for merge-worktree tests.

Used by tests in test_merge_worktree_prepare.py to seed minimal DB state for
preflight gate tests. Tests that need richer state should add their helpers
alongside or extend these.
"""
from __future__ import annotations

import os
from pathlib import Path

from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain.item_test_results_classify import (
    format_verdict_head_sha_trailer,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.merge_worktree_test_rest_fakes import DEFAULT_HEAD_SHA


TEST_ITEM_ID = 42
TEST_BRANCH = f"YOK-{TEST_ITEM_ID}"

# Verdict seeded into ``items.test_results`` for merge-mechanics tests. The
# freshness-bound merge gate accepts a local PASS substitute only when its
# stamped head-SHA matches the PR head SHA the REST fake reports
# (``DEFAULT_HEAD_SHA``), so the seed carries that binding — modelling a
# correct polish output rather than a legacy unbound verdict.
_SEEDED_FRESH_VERDICT = (
    "============================== 1 passed in 0.01s "
    "==============================\n\n"
    + format_verdict_head_sha_trailer(DEFAULT_HEAD_SHA)
)


def _sql(conn, statement: str) -> str:
    from yoke_core.domain import db_backend

    if db_backend.connection_is_postgres(conn):
        return statement.replace("?", "%s")
    return statement


def _seed_yoke_project_with_pat(conn, *, repo_path: str, item_id: int,
                                  branch: str) -> None:
    """Seed projects + github capability + literal token secret + items row.

    Shared by the merge_env fixture and the standalone epic-tasks helper so
    the REST PAT precondition resolves the same way on every test DB.
    """
    conn.execute(
        "DELETE FROM capability_secrets "
        "WHERE project_id = 1 AND type = 'github' AND key = 'token'"
    )
    conn.execute(
        "DELETE FROM project_capabilities "
        "WHERE project_id = 1 AND type = 'github'"
    )
    # The generic test-DB seed declares a ci_workflow_file capability
    # (mirroring prod). These merge-engine subprocess fixtures are no-CI
    # by intent — with the CI-declaration check repaired (field-note
    # 12951), a declared workflow makes every merge wait the full
    # ci_registration_timeout for check-runs that can never register.
    conn.execute(
        "DELETE FROM project_capabilities "
        "WHERE project_id = 1 AND type = 'ci_workflow_file'"
    )
    conn.execute(_sql(conn, "DELETE FROM items WHERE id = ?"), (item_id,))
    conn.execute(
        _sql(
            conn,
            "INSERT INTO projects "
            "(id, slug, name, github_repo, created_at) "
            "VALUES (1, 'yoke', 'yoke', 'anthropics/yoke', "
            "'2026-01-01T00:00:00Z') "
            "ON CONFLICT(id) DO UPDATE SET "
            "slug = EXCLUDED.slug, "
            "name = EXCLUDED.name, "
            "github_repo = EXCLUDED.github_repo, "
            "created_at = EXCLUDED.created_at",
        ),
    )
    register_machine_checkout(
        Path(repo_path) / f".yoke-test-config-{os.getpid()}-{item_id}",
        Path(repo_path),
        1,
    )
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, created_at) "
        "VALUES (1, 'github', '2026-01-01T00:00:00Z') "
        "ON CONFLICT(project_id, type) DO UPDATE SET "
        "created_at = EXCLUDED.created_at"
    )
    conn.execute(
        "INSERT INTO capability_secrets "
        "(project_id, type, key, source, value, created_at) "
        "VALUES (1, 'github', 'token', 'literal', "
        "'ghp_test_token', '2026-01-01T00:00:00Z') "
        "ON CONFLICT(project_id, type, key) DO UPDATE SET "
        "source = EXCLUDED.source, "
        "value = EXCLUDED.value, "
        "created_at = EXCLUDED.created_at"
    )
    conn.execute(
        _sql(
            conn,
            "INSERT INTO items "
            "(id, title, type, status, project_id, project_sequence, "
            "created_at, updated_at, test_results) "
            "VALUES (?, ?, 'issue', 'implementing', 1, ?, "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "title = EXCLUDED.title, "
            "type = EXCLUDED.type, "
            "status = EXCLUDED.status, "
            "project_id = EXCLUDED.project_id, "
            "project_sequence = EXCLUDED.project_sequence, "
            "updated_at = EXCLUDED.updated_at, "
            "test_results = EXCLUDED.test_results",
        ),
        (
            item_id,
            f"Test item {branch}",
            item_id,
            _SEEDED_FRESH_VERDICT,
        ),
    )


def _create_epic_tasks_db(db_path: Path, task_status: str = "implementing") -> None:
    """Create a minimal DB with epic_tasks for pre-flight tests."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect(path=str(db_path))
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE IF NOT EXISTS merge_locks (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            branch TEXT NOT NULL,
            epic_id TEXT,
            acquired_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS epic_tasks (
            id INTEGER PRIMARY KEY,
            epic_id INTEGER NOT NULL,
            task_num INTEGER NOT NULL,
            title TEXT,
            worktree TEXT,
            context_estimate TEXT,
            dependencies TEXT,
            status TEXT DEFAULT 'planned',
            dispatch_attempts INTEGER DEFAULT 0,
            body TEXT, github_issue TEXT, branch TEXT, worktree_path TEXT,
            blocked_by TEXT, max_attempts INTEGER DEFAULT 5,
            agent_id TEXT, last_heartbeat TEXT,
            UNIQUE(epic_id, task_num)
        );
        CREATE TABLE IF NOT EXISTS qa_requirements (
            id INTEGER PRIMARY KEY,
            item_id INTEGER, epic_id INTEGER, task_num INTEGER,
            deployment_run_id TEXT, qa_kind TEXT NOT NULL,
            qa_phase TEXT NOT NULL, target_env TEXT,
            blocking_mode TEXT NOT NULL DEFAULT 'blocking',
            requirement_source TEXT NOT NULL DEFAULT 'explicit',
            success_policy TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS qa_runs (
            id INTEGER PRIMARY KEY,
            qa_requirement_id INTEGER NOT NULL,
            executor_type TEXT,
            qa_kind TEXT,
            verdict TEXT, raw_result TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT, completed_at TEXT
        );
    """
    )
    conn.execute("DELETE FROM qa_runs")
    conn.execute("DELETE FROM qa_requirements")
    conn.execute(_sql(conn, "DELETE FROM epic_tasks WHERE epic_id = ?"), (TEST_ITEM_ID,))
    conn.execute(
        _sql(
            conn,
            "INSERT INTO epic_tasks (epic_id, task_num, title, worktree, status) "
            "VALUES (?, 1, 'Task 1', ?, ?);",
        ),
        (TEST_ITEM_ID, TEST_BRANCH, task_status),
    )
    # Seed projects + github capability + secret + items so the REST
    # transport's PAT precondition resolves; tests stub REST responses via
    # the merge_env fixture's per-test rest_fake_dir.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            github_repo TEXT,
            public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
            breakage_policy TEXT NOT NULL DEFAULT 'founder_cutover',
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_capabilities (
            project_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z',
            PRIMARY KEY (project_id, type)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capability_secrets (
            project_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            key TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'literal'
                CHECK(source = 'literal'),
            value TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z',
            PRIMARY KEY (project_id, type, key)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL DEFAULT 'issue',
            status TEXT NOT NULL DEFAULT 'idea',
            project_id INTEGER NOT NULL DEFAULT 1,
            project_sequence INTEGER NOT NULL DEFAULT 42,
            test_results TEXT,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z',
            updated_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
        );
        """
    )
    _seed_yoke_project_with_pat(
        conn,
        repo_path="/tmp",
        item_id=TEST_ITEM_ID,
        branch=TEST_BRANCH,
    )
    conn.commit()
    conn.close()


def _insert_canonical_integration_simulation(db_path: Path) -> None:
    """Insert a canonical integration simulation qa_requirement + qa_run."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect(path=str(db_path))
    conn.execute(
        """
        INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, target_env, blocking_mode, requirement_source, success_policy, created_at)
        VALUES (42, 'simulation', 'verification', 'local', 'blocking', 'explicit',
                '{"type":"deterministic","criteria":"result_pass","phase":"integration"}',
                '2026-04-20T00:00:00Z');
        """
    )
    req_id = conn.execute(
        "SELECT id FROM qa_requirements WHERE item_id = 42 AND qa_kind = 'simulation' ORDER BY id DESC LIMIT 1;"
    ).fetchone()[0]
    conn.execute(
        _sql(
            conn,
            """
        INSERT INTO qa_runs (qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at)
        VALUES (?, 'agent', 'simulation', 'pass',
                '{"body":"## Result: CLEAN","phase":"integration"}',
                '2026-04-20T00:00:00Z');
        """,
        ),
        (req_id,),
    )
    conn.commit()
    conn.close()


def _insert_plain_text_integration_simulation(db_path: Path) -> None:
    """Insert a plain-text (non-canonical) simulation qa_requirement + qa_run."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect(path=str(db_path))
    conn.execute(
        """
        INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, target_env, blocking_mode, requirement_source, success_policy, created_at)
        VALUES (42, 'simulation', 'verification', 'local', 'blocking', 'explicit',
                '{"type":"deterministic","criteria":"result_pass","phase":"integration"}',
                '2026-04-20T00:00:00Z');
        """
    )
    req_id = conn.execute(
        "SELECT id FROM qa_requirements WHERE item_id = 42 AND qa_kind = 'simulation' ORDER BY id DESC LIMIT 1;"
    ).fetchone()[0]
    conn.execute(
        _sql(
            conn,
            """
        INSERT INTO qa_runs (qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at)
        VALUES (?, 'agent', 'simulation', 'pass',
                'All 6 epic tasks completed and verified',
                '2026-04-20T00:00:00Z');
        """,
        ),
        (req_id,),
    )
    conn.commit()
    conn.close()
