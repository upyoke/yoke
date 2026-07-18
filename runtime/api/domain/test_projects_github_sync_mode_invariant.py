"""Safe project sync-mode creation and enablement."""

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
        github_repo="Example/ExternalWebapp",
        default_branch="main",
        installation_status="active",
    )


def _bind_externalwebapp() -> None:
    cmd_bind_project_repo(
        "externalwebapp",
        installation_id="8801",
        repository_id="7701",
        github_repo="Example/ExternalWebapp",
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
        slug="externalwebapp",
        name="ExternalWebapp",
        github_sync_mode="backlog_only",
        mode="update",
    )

    with pytest.raises(GithubSyncModeError, match="active, verified"):
        cmd_upsert(
            slug="externalwebapp",
            name="ExternalWebapp",
            github_sync_mode="enabled",
            mode="update",
        )
    with pytest.raises(GithubSyncModeError, match="active, verified"):
        cmd_update("externalwebapp", "github_sync_mode", "enabled")

    _bind_externalwebapp()
    result = cmd_upsert(
        slug="externalwebapp",
        name="ExternalWebapp",
        github_sync_mode="enabled",
        mode="update",
    )
    assert result["project"]["github_sync_mode"] == "enabled"
    assert cmd_update("externalwebapp", "github_sync_mode", "enabled").startswith(
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
