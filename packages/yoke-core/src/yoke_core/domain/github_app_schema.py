"""Canonical schema for GitHub App installations and project bindings."""

from __future__ import annotations

from yoke_contracts.github_origin import DEFAULT_GITHUB_API_URL

from yoke_core.domain.schema_common import _add_column_if_not_exists


GITHUB_APP_INSTALLATIONS_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS github_app_installations (
    installation_id TEXT PRIMARY KEY,
    api_url TEXT NOT NULL DEFAULT '{DEFAULT_GITHUB_API_URL}',
    account_id TEXT NOT NULL,
    account_login TEXT NOT NULL,
    account_type TEXT NOT NULL,
    repository_selection TEXT NOT NULL DEFAULT 'selected',
    permissions TEXT NOT NULL DEFAULT '{{}}',
    status TEXT NOT NULL DEFAULT 'active',
    last_verified_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

PROJECT_GITHUB_REPO_BINDINGS_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS project_github_repo_bindings (
    project_id INTEGER PRIMARY KEY REFERENCES projects(id),
    installation_id TEXT NOT NULL
        REFERENCES github_app_installations(installation_id),
    repository_id TEXT NOT NULL,
    api_url TEXT NOT NULL DEFAULT '{DEFAULT_GITHUB_API_URL}',
    github_repo TEXT NOT NULL,
    default_branch TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    permissions TEXT NOT NULL DEFAULT '{{}}',
    last_verified_at TEXT,
    last_error TEXT,
    last_sync_at TEXT,
    last_sync_outcome TEXT,
    last_sync_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(installation_id, github_repo)
)
"""

PROJECT_GITHUB_REPOSITORY_ID_UNIQUE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_project_github_repo_bindings_installation_repository_id
ON project_github_repo_bindings(installation_id, repository_id)
"""

GITHUB_APP_SCHEMA_SQL = (
    f"{GITHUB_APP_INSTALLATIONS_CREATE_SQL};\n"
    f"{PROJECT_GITHUB_REPO_BINDINGS_CREATE_SQL};\n"
    f"{PROJECT_GITHUB_REPOSITORY_ID_UNIQUE_INDEX_SQL};"
)


def create_github_app_tables(conn) -> None:
    """Converge the additive GitHub App tables on every control-plane boot."""
    conn.execute(GITHUB_APP_INSTALLATIONS_CREATE_SQL)
    conn.execute(PROJECT_GITHUB_REPO_BINDINGS_CREATE_SQL)
    api_url_column = f"TEXT NOT NULL DEFAULT '{DEFAULT_GITHUB_API_URL}'"
    _add_column_if_not_exists(
        conn,
        "github_app_installations",
        "api_url",
        api_url_column,
    )
    _add_column_if_not_exists(
        conn,
        "project_github_repo_bindings",
        "api_url",
        api_url_column,
    )
    for name in ("last_sync_at", "last_sync_outcome", "last_sync_error"):
        _add_column_if_not_exists(
            conn,
            "project_github_repo_bindings",
            name,
            "TEXT",
        )
    conn.execute(PROJECT_GITHUB_REPOSITORY_ID_UNIQUE_INDEX_SQL)


__all__ = [
    "GITHUB_APP_INSTALLATIONS_CREATE_SQL",
    "GITHUB_APP_SCHEMA_SQL",
    "PROJECT_GITHUB_REPO_BINDINGS_CREATE_SQL",
    "PROJECT_GITHUB_REPOSITORY_ID_UNIQUE_INDEX_SQL",
    "create_github_app_tables",
]
