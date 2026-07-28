"""Database helper functions for merge-worktree tests.

Used by tests in test_merge_worktree_prepare.py to seed minimal DB state for
preflight gate tests. Tests that need richer state should add their helpers
alongside or extend these.
"""

from __future__ import annotations

import os
from pathlib import Path

from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.merge_worktree_simulation_test_db import (
    _insert_canonical_integration_simulation as _insert_canonical_integration_simulation,
    _insert_plain_text_integration_simulation as _insert_plain_text_integration_simulation,
    _sql,
)
from yoke_core.domain.item_test_results_classify import (
    format_verdict_head_sha_trailer,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.merge_worktree_test_rest_fakes import DEFAULT_HEAD_SHA
from yoke_contracts.github_app_installation_permissions import (
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.project_github_binding import cmd_bind_project_repo


TEST_ITEM_ID = 42
TEST_BRANCH = f"YOK-{TEST_ITEM_ID}"

# Verdict seeded into ``items.test_results`` for merge-mechanics tests. The
# freshness-bound merge gate accepts a local PASS substitute only when its
# stamped head-SHA matches the PR head SHA the REST fake reports
# (``DEFAULT_HEAD_SHA``), so the seed carries that binding — modelling a
# correct freshness-bound polish output.
_SEEDED_FRESH_VERDICT = (
    "============================== 1 passed in 0.01s "
    "==============================\n\n"
    + format_verdict_head_sha_trailer(DEFAULT_HEAD_SHA)
)


def _seed_yoke_project_with_github_app(
    conn,
    *,
    repo_path: str,
    item_id: int,
    branch: str,
) -> None:
    """Seed a project App binding plus the merge fixture's item row.

    The merge subprocess binds a transient App user token through its test
    entrypoint; no long-lived project credential is stored in the database.
    """
    # The generic test-DB seed declares a ci_workflow_file capability
    # (mirroring prod). These merge-engine subprocess fixtures are no-CI
    # by intent: a declared workflow would make every merge wait the full
    # ci_registration_timeout for check-runs that cannot register here.
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
    verified = VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="anthropics",
        account_type="Organization",
        repository_selection="selected",
        permissions=dict(REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS),
        repository_id="4567",
        github_repo="anthropics/yoke",
        default_branch="main",
    )
    cmd_bind_project_repo(
        "yoke",
        installation_id=verified.installation_id,
        repository_id=verified.repository_id,
        github_repo=verified.github_repo,
        expected_api_url="https://api.github.com",
        github_user_access_token="transient-test-user-token",
        verifier=lambda **_kwargs: verified,
        conn=conn,
    )
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    workflow_id, workflow_version_id = resolve_current_workflow_pin(conn, "issue")
    # Merge-mechanics fixtures exercise the local-verification fallback. The
    # minimal disposable schema omits its scalar evidence field, so extend only
    # the test database and leave production schema authority unchanged.
    conn.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS test_results TEXT")
    conn.execute(
        _sql(
            conn,
            "INSERT INTO items "
            "(id, title, workflow_id, workflow_version_id, status, "
            "project_id, project_sequence, "
            "created_at, updated_at, test_results) "
            "VALUES (?, ?, ?, ?, 'implementing', 1, ?, "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "title = EXCLUDED.title, "
            "workflow_id = EXCLUDED.workflow_id, "
            "workflow_version_id = EXCLUDED.workflow_version_id, "
            "status = EXCLUDED.status, "
            "project_id = EXCLUDED.project_id, "
            "project_sequence = EXCLUDED.project_sequence, "
            "updated_at = EXCLUDED.updated_at, "
            "test_results = EXCLUDED.test_results",
        ),
        (
            item_id,
            f"Test item {branch}",
            workflow_id,
            workflow_version_id,
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
            item_worktree_id INTEGER,
            context_estimate TEXT,
            dependencies TEXT,
            status TEXT DEFAULT 'planned',
            dispatch_attempts INTEGER DEFAULT 0,
            body TEXT, github_issue TEXT,
            blocked_by TEXT, max_attempts INTEGER DEFAULT 5,
            agent_id TEXT, last_heartbeat TEXT,
            UNIQUE(epic_id, task_num)
        );
        CREATE TABLE IF NOT EXISTS item_worktrees (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL,
            branch TEXT NOT NULL,
            path TEXT,
            lane_role TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            released_at TEXT
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
    """,
    )
    conn.execute("DELETE FROM qa_runs")
    conn.execute("DELETE FROM qa_requirements")
    conn.execute(
        _sql(conn, "DELETE FROM epic_tasks WHERE epic_id = ?"), (TEST_ITEM_ID,)
    )
    # Seed projects + a GitHub App binding + items so the REST transport's
    # auth precondition resolves; tests stub REST responses via the merge_env
    # fixture's per-test rest_fake_dir.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            github_repo TEXT,
            default_branch TEXT DEFAULT 'main',
            github_sync_mode TEXT NOT NULL DEFAULT 'enabled',
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
            settings TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z',
            PRIMARY KEY (project_id, type)
        );
        """
    )
    from yoke_core.domain.github_app_schema import create_github_app_tables

    create_github_app_tables(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            workflow_id TEXT,
            workflow_version_id INTEGER,
            status TEXT NOT NULL DEFAULT 'idea',
            project_id INTEGER NOT NULL DEFAULT 1,
            project_sequence INTEGER NOT NULL DEFAULT 42,
            test_results TEXT,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z',
            updated_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
        );
        """
    )
    from runtime.api.api_workflow_test_helpers import (
        install_workflow_registry_and_pin_items,
    )

    install_workflow_registry_and_pin_items(conn)
    _seed_yoke_project_with_github_app(
        conn,
        repo_path="/tmp",
        item_id=TEST_ITEM_ID,
        branch=TEST_BRANCH,
    )
    conn.execute(
        _sql(
            conn,
            "INSERT INTO item_worktrees "
            "(id, item_id, branch, path, lane_role, state, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'worker', 'active', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z') "
            "ON CONFLICT (id) DO UPDATE SET branch = EXCLUDED.branch, "
            "path = EXCLUDED.path, state = EXCLUDED.state, "
            "updated_at = EXCLUDED.updated_at",
        ),
        (TEST_ITEM_ID, TEST_ITEM_ID, TEST_BRANCH, f"/tmp/{TEST_BRANCH}"),
    )
    conn.execute(
        _sql(
            conn,
            "INSERT INTO epic_tasks "
            "(epic_id, task_num, title, item_worktree_id, status) "
            "VALUES (?, 1, 'Task 1', ?, ?);",
        ),
        (TEST_ITEM_ID, TEST_ITEM_ID, task_status),
    )
    conn.commit()
    conn.close()
