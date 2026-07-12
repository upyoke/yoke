"""Legacy project GitHub sync-mode repair behavior."""

from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain import db_backend
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.project_github_binding import cmd_bind_project_repo
from yoke_core.domain.projects_crud import cmd_get
from yoke_core.domain.projects_github_sync_mode_repair import (
    REPAIR_ACTION_CLEAR_REPO_PROJECTION,
    REPAIR_ACTION_REMOVE_CAPABILITY_PROJECTION,
    REPAIR_ACTION_SET_BACKLOG_ONLY,
    cmd_repair_unbound_enabled_sync_modes,
)


@pytest.fixture
def project_db(monkeypatch):
    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            pg_testdb.dsn_for_test_database(db_name),
        )
        yield db_name
    finally:
        pg_testdb.drop_test_database(db_name)


def _verified() -> VerifiedProjectGitHubBinding:
    return VerifiedProjectGitHubBinding(
        installation_id="8801",
        account_id="991",
        account_login="Example",
        account_type="Organization",
        repository_selection="selected",
        permissions={
            "metadata": "read",
            "issues": "write",
            "pull_requests": "write",
            "contents": "write",
            "actions": "write",
            "checks": "read",
            "workflows": "write",
            "secrets": "write",
            "actions_variables": "write",
        },
        repository_id="7701",
        github_repo="Example/Buzz",
        default_branch="main",
        installation_status="active",
    )


def _bind(project: str, verified: VerifiedProjectGitHubBinding) -> None:
    cmd_bind_project_repo(
        project,
        installation_id=verified.installation_id,
        repository_id=verified.repository_id,
        github_repo=verified.github_repo,
        expected_api_url="https://api.github.com",
        github_user_access_token="short-lived-user-token",
        verifier=lambda **_kwargs: verified,
    )


def test_repair_normalizes_only_effectively_enabled_unbound_rows(project_db):
    _bind("buzz", _verified())
    conn = pg_testdb.connect_test_database(project_db)
    try:
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix, github_sync_mode, created_at) "
            "VALUES (501, 'legacy-enabled', 'Legacy Enabled', 'LEN', "
            "'enabled', '2026-01-01T00:00:00Z'), "
            "(502, 'already-safe', 'Already Safe', 'SAF', "
            "'backlog_only', '2026-01-01T00:00:00Z')"
        )
        conn.commit()

        preview = cmd_repair_unbound_enabled_sync_modes(conn=conn)
        assert preview["applied"] is False
        assert preview["normalized"] == 0
        assert {row["slug"] for row in preview["projects"]} == {
            "yoke",
            "legacy-enabled",
        }
        assert (
            conn.execute(
                "SELECT github_sync_mode FROM projects WHERE slug='yoke'"
            ).fetchone()[0]
            is None
        )

        repaired = cmd_repair_unbound_enabled_sync_modes(conn=conn, apply=True)
        assert repaired["matched"] == 2
        assert repaired["normalized"] == 2
        rows = conn.execute(
            "SELECT slug, github_sync_mode FROM projects "
            "WHERE slug IN ('yoke', 'buzz', 'legacy-enabled', 'already-safe')"
        ).fetchall()
        assert {row["slug"]: row["github_sync_mode"] for row in rows} == {
            "yoke": "backlog_only",
            "buzz": None,
            "legacy-enabled": "backlog_only",
            "already-safe": "backlog_only",
        }
    finally:
        conn.close()


def test_repair_can_target_one_project(project_db):
    report = cmd_repair_unbound_enabled_sync_modes(project="yoke", apply=True)

    assert report["matched"] == 1
    assert report["normalized"] == 1
    assert [row["slug"] for row in report["projects"]] == ["yoke"]
    assert cmd_get("yoke", "github_sync_mode") == "backlog_only"


def test_repair_converges_unbound_projections_idempotently(project_db):
    verified = replace(
        _verified(),
        repository_id="7702",
        github_repo="Example/Yoke",
    )
    _bind("yoke", verified)
    conn = pg_testdb.connect_test_database(project_db)
    try:
        conn.execute(
            "UPDATE projects SET github_repo=%s, github_sync_mode=NULL "
            "WHERE slug='buzz'",
            ("beebauman/buzz",),
        )
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            "VALUES (2, 'github', %s)",
            ('{"repo_owner":"beebauman","repo_name":"buzz"}',),
        )
        conn.execute(
            "INSERT INTO capability_secrets "
            "(project_id, type, key, value, source) "
            "VALUES (2, 'github', 'token', 'stranded-token', 'literal')"
        )
        conn.commit()

        preview = cmd_repair_unbound_enabled_sync_modes(project="buzz", conn=conn)

        assert preview == {
            "applied": False,
            "matched": 1,
            "normalized": 0,
            "projects": [
                {
                    "id": 2,
                    "slug": "buzz",
                    "stored_mode": None,
                    "effective_mode": "enabled",
                    "bound": False,
                    "active_verified_binding": False,
                    "actions": [
                        {
                            "action": REPAIR_ACTION_SET_BACKLOG_ONLY,
                            "column": "github_sync_mode",
                            "from": None,
                            "to": "backlog_only",
                        },
                        {
                            "action": REPAIR_ACTION_CLEAR_REPO_PROJECTION,
                            "column": "github_repo",
                            "from": "beebauman/buzz",
                            "to": None,
                        },
                        {
                            "action": REPAIR_ACTION_REMOVE_CAPABILITY_PROJECTION,
                            "table": "project_capabilities",
                            "type": "github",
                        },
                    ],
                }
            ],
        }
        repaired = cmd_repair_unbound_enabled_sync_modes(
            project="buzz",
            apply=True,
            conn=conn,
        )

        assert repaired["matched"] == 1
        assert repaired["normalized"] == 1
        repaired_project = conn.execute(
            "SELECT github_repo, github_sync_mode FROM projects WHERE id=2"
        ).fetchone()
        assert dict(repaired_project) == {
            "github_repo": None,
            "github_sync_mode": "backlog_only",
        }
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM project_capabilities "
                "WHERE project_id=2 AND type='github'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT value FROM capability_secrets "
                "WHERE project_id=2 AND type='github' AND key='token'"
            ).fetchone()[0]
            == "stranded-token"
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM github_app_installations "
                "WHERE installation_id='8801'"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM project_github_repo_bindings "
                "WHERE project_id=1 AND installation_id='8801'"
            ).fetchone()[0]
            == 1
        )

        repeated = cmd_repair_unbound_enabled_sync_modes(
            project="buzz",
            apply=True,
            conn=conn,
        )
        assert repeated == {
            "applied": True,
            "matched": 0,
            "normalized": 0,
            "projects": [],
        }
    finally:
        conn.close()
