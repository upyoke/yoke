"""GitHub App tables for the composed Postgres fixture schema."""

from yoke_contracts.github_origin import DEFAULT_GITHUB_API_URL


_GITHUB_APP_DDL = f"""
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
);
CREATE TABLE IF NOT EXISTS project_github_repo_bindings (
    project_id INTEGER PRIMARY KEY,
    installation_id TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    api_url TEXT NOT NULL DEFAULT '{DEFAULT_GITHUB_API_URL}',
    github_repo TEXT NOT NULL,
    default_branch TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    permissions TEXT NOT NULL DEFAULT '{{}}',
    last_verified_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_sync_at TEXT,
    last_sync_outcome TEXT,
    last_sync_error TEXT,
    UNIQUE(installation_id, github_repo)
);
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_project_github_repo_bindings_installation_repository_id
ON project_github_repo_bindings(installation_id, repository_id);
"""

__all__ = ("_GITHUB_APP_DDL",)
