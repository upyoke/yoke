"""Safe project sync-mode creation, enablement, and legacy repair."""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain import db_backend
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.project_github_binding import cmd_bind_project_repo
from yoke_core.domain.projects_crud import cmd_create, cmd_get, cmd_update
from yoke_core.domain.projects_github_sync_mode import GithubSyncModeError
from yoke_core.domain.projects_github_sync_mode_repair import (
    cmd_repair_unbound_enabled_sync_modes,
)
from yoke_core.domain.projects_upsert import cmd_upsert


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


def _bind_buzz() -> None:
    cmd_bind_project_repo(
        "buzz",
        installation_id="8801",
        repository_id="7701",
        github_repo="Example/Buzz",
        expected_api_url="https://api.github.com",
        github_user_access_token="short-lived-user-token",
        verifier=lambda **_kwargs: _verified(),
    )


def test_authoritative_and_legacy_creates_default_backlog_only(project_db):
    result = cmd_upsert(slug="new-safe", name="New Safe", mode="create")

    assert result["created"] is True
    assert result["project"]["github_sync_mode"] == "backlog_only"

    assert cmd_create("legacy-safe", "Legacy Safe") == ("Created project: legacy-safe")
    assert cmd_get("legacy-safe", "github_sync_mode") == "backlog_only"


def test_create_rejects_explicit_enabled_without_binding(project_db):
    with pytest.raises(ValueError, match="active, verified"):
        cmd_upsert(
            slug="unsafe-create",
            name="Unsafe Create",
            github_sync_mode="enabled",
            mode="create",
        )

    conn = pg_testdb.connect_test_database(project_db)
    try:
        row = conn.execute(
            "SELECT id FROM projects WHERE slug='unsafe-create'"
        ).fetchone()
        assert row is None
    finally:
        conn.close()


def test_enabled_updates_require_active_verified_binding(project_db):
    cmd_upsert(
        slug="buzz",
        name="Buzz",
        github_sync_mode="backlog_only",
        mode="update",
    )

    with pytest.raises(GithubSyncModeError, match="active, verified"):
        cmd_upsert(
            slug="buzz",
            name="Buzz",
            github_sync_mode="enabled",
            mode="update",
        )
    with pytest.raises(GithubSyncModeError, match="active, verified"):
        cmd_update("buzz", "github_sync_mode", "enabled")

    _bind_buzz()
    result = cmd_upsert(
        slug="buzz",
        name="Buzz",
        github_sync_mode="enabled",
        mode="update",
    )
    assert result["project"]["github_sync_mode"] == "enabled"
    assert cmd_update("buzz", "github_sync_mode", "enabled").startswith(
        "Updated project"
    )


def test_omitted_update_does_not_silently_repair_existing_mode(project_db):
    conn = pg_testdb.connect_test_database(project_db)
    try:
        conn.execute("UPDATE projects SET github_sync_mode='enabled' WHERE slug='yoke'")
        conn.commit()
    finally:
        conn.close()

    result = cmd_upsert(slug="yoke", name="Yoke Renamed", mode="update")

    assert result["project"]["github_sync_mode"] == "enabled"


def test_repair_normalizes_only_effectively_enabled_unbound_rows(project_db):
    _bind_buzz()
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
        modes = {row["slug"]: row["github_sync_mode"] for row in rows}
        assert modes == {
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
