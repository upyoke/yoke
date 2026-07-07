"""Project-registry table DDL.

Holds the ``CREATE TABLE`` text used by
:func:`yoke_core.domain.projects_restart.cmd_init`.  Kept separate so
``projects_restart.py`` retains line-count headroom for future migration
helpers.
"""

from __future__ import annotations


def _projects_table_sql(*, if_not_exists: bool) -> str:
    clause = "IF NOT EXISTS " if if_not_exists else ""
    # github_sync_mode: per-project GitHub sync switch (enabled |
    # backlog_only); NULL resolves to enabled through
    # yoke_core.domain.projects_github_sync_mode. Pre-existing DBs gain
    # the column via the idempotent schema-init migrations.
    return f"""
        CREATE TABLE {clause}projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL,
            name TEXT NOT NULL,
            emoji TEXT DEFAULT '',
            default_branch TEXT DEFAULT 'main',
            github_repo TEXT,
            public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
            github_sync_mode TEXT,
            created_at TEXT NOT NULL
        );
    """


_INIT_TABLES_SQL = f"""
            {_projects_table_sql(if_not_exists=True)}

            CREATE TABLE IF NOT EXISTS sites (
                id TEXT PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                settings TEXT DEFAULT '{{}}'
            );

            CREATE TABLE IF NOT EXISTS environments (
                id TEXT PRIMARY KEY,
                site TEXT NOT NULL REFERENCES sites(id),
                name TEXT NOT NULL,
                url TEXT,
                deploy_method TEXT,
                deploy_command TEXT,
                health_check_url TEXT,
                config_notes TEXT,
                last_deployed_at TEXT,
                created_at TEXT NOT NULL,
                settings TEXT DEFAULT '{{}}',
                UNIQUE(site, name)
            );

            CREATE TABLE IF NOT EXISTS capability_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                required_config TEXT NOT NULL,
                requires TEXT DEFAULT '[]',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_capabilities (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                type TEXT NOT NULL,
                settings TEXT DEFAULT '{{}}',
                verified_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, type)
            );

            CREATE TABLE IF NOT EXISTS ephemeral_environments (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id),
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

            CREATE TABLE IF NOT EXISTS capability_secrets (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                type TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'literal'
                    CHECK(source = 'literal'),
                created_at TEXT NOT NULL,
                UNIQUE(project_id, type, key)
            );
        """
