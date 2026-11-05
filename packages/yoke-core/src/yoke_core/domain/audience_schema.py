"""Stored audiences describe people; their consumers own actions and policy."""

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


def create_audience_tables(conn: Any, *, commit: bool = True) -> None:
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS audiences (
            id INTEGER PRIMARY KEY,
            project_id INTEGER REFERENCES projects(id),
            org_id INTEGER REFERENCES organizations(id),
            name TEXT,
            CHECK ((project_id IS NOT NULL AND org_id IS NULL)
                OR (project_id IS NULL AND org_id IS NOT NULL))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_audiences_project_name
            ON audiences(project_id, name) WHERE name IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_audiences_org_name
            ON audiences(org_id, name) WHERE name IS NOT NULL;
        CREATE TABLE IF NOT EXISTS audience_rules (
            audience_id INTEGER NOT NULL REFERENCES audiences(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            scope_kind TEXT NOT NULL CHECK(scope_kind IN ('org', 'project', 'actor')),
            scope_id INTEGER NOT NULL,
            role_name TEXT,
            CHECK (scope_kind <> 'actor' OR role_name IS NULL),
            PRIMARY KEY (audience_id, position)
        );
        CREATE INDEX IF NOT EXISTS idx_audience_rules_scope
            ON audience_rules(scope_kind, scope_id, role_name, audience_id);
    """,
    )
    if commit:
        conn.commit()
