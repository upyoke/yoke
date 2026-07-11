"""GitHub App table entries for the project schema packet topic."""

from __future__ import annotations


GITHUB_APP_TABLES: dict[str, dict] = {
    "github_app_installations": {
        "columns": [
            ("installation_id", "TEXT"),
            ("api_url", "TEXT"),
            ("account_id", "TEXT"),
            ("account_login", "TEXT"),
            ("account_type", "TEXT"),
            ("repository_selection", "TEXT"),
            ("permissions", "TEXT"),
            ("status", "TEXT"),
            ("last_verified_at", "TEXT"),
            ("last_error", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "notes": (
            "Control-plane GitHub App installation state keyed by the TEXT "
            "`installation_id`; there is no numeric `id` column. `permissions` "
            "is a JSON object, `api_url` is the verified GitHub deployment API "
            "base, and `status` is active, pending, suspended, or "
            "deleted. Join project bindings on `installation_id`; never read "
            "App private keys or user refresh credentials from this table."
        ),
    },
    "project_github_repo_bindings": {
        "columns": [
            ("project_id", "INTEGER"),
            ("installation_id", "TEXT"),
            ("repository_id", "TEXT"),
            ("api_url", "TEXT"),
            ("github_repo", "TEXT"),
            ("default_branch", "TEXT"),
            ("status", "TEXT"),
            ("permissions", "TEXT"),
            ("last_verified_at", "TEXT"),
            ("last_error", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "notes": (
            "One GitHub App repository binding per project, keyed by INTEGER "
            "`project_id`. `repository_id` and `installation_id` are TEXT "
            "identifiers; `api_url` is the verified GitHub deployment API base; "
            "`permissions` is a JSON object. A pending or "
            "unavailable binding keeps `projects.github_sync_mode` backlog-only. "
            "The wrong guessed table name `project_github_bindings` does not "
            "exist; use this `_repo_` table. Registered functions are "
            "`projects.github_binding.bind`, `projects.github_binding.status`, "
            "and `projects.github_binding.unbind`; sync-mode drift is repaired "
            "through `projects.github_sync_mode.repair`."
        ),
    },
}


__all__ = ["GITHUB_APP_TABLES"]
