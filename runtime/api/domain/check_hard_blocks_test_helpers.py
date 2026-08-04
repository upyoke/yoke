"""Database fixture for hard-block dependency tests."""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.workflow_registry import (
    canonical_definition_json,
    definition_digest,
)

_SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL,
    workflow_id TEXT NOT NULL DEFAULT 'issue',
    workflow_version_id INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'idea',
    priority TEXT NOT NULL DEFAULT 'medium',
    project_id INTEGER NOT NULL DEFAULT 1,
    project_sequence INTEGER NOT NULL, merged_at TEXT
);
CREATE TABLE item_worktrees (
    id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL,
    branch TEXT NOT NULL, path TEXT, lane_role TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, released_at TEXT
);
CREATE TABLE workflow_versions (
    id INTEGER PRIMARY KEY, workflow_id TEXT NOT NULL,
    version INTEGER NOT NULL, definition_json TEXT NOT NULL,
    definition_digest TEXT NOT NULL
);
CREATE TABLE item_dependencies (
    id INTEGER PRIMARY KEY, dependent_item TEXT NOT NULL,
    blocking_item TEXT NOT NULL, gate_point TEXT NOT NULL,
    satisfaction TEXT NOT NULL
);
CREATE TABLE projects (
    id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
);
INSERT INTO projects (id, slug, name)
VALUES (1, 'yoke', 'Yoke') ON CONFLICT(id) DO NOTHING;
"""


def apply_hard_block_schema() -> None:
    """Build the workflow-pinned dependency fixture."""
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _SCHEMA)
        fixture = builtin_workflow_definition("issue")
        definition = fixture["definition"]
        conn.execute(
            "INSERT INTO workflow_versions "
            "(id, workflow_id, version, definition_json, definition_digest) "
            "VALUES (1, 'issue', %s, %s, %s)",
            (
                int(fixture["canon_version"]),
                canonical_definition_json(definition),
                definition_digest(definition),
            ),
        )
        conn.commit()
    finally:
        conn.close()


__all__ = ["apply_hard_block_schema"]
