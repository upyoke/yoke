"""Schema for operator-authored workflow execution instructions.

An instruction is a block of operator prose that agents must obey when
executing items. Scope is declarative: junction rows bind an instruction
to one or more workflows, and either the ``applies_to_all_projects``
predicate or explicit project junction rows select which projects see
it. Membership is resolved at read time — the all-projects predicate is
never materialized into per-project rows, so new projects are covered
automatically.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE = "workflow_execution_instructions"
INSTRUCTION_WORKFLOWS_TABLE = "workflow_execution_instruction_workflows"
INSTRUCTION_PROJECTS_TABLE = "workflow_execution_instruction_projects"

WORKFLOW_EXECUTION_INSTRUCTIONS_TABLES_SQL = f"""
CREATE TABLE IF NOT EXISTS {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    applies_to_all_projects INTEGER NOT NULL DEFAULT 0,
    ordering INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active','disabled')),
    updated_by_actor_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS {INSTRUCTION_WORKFLOWS_TABLE} (
    instruction_id INTEGER NOT NULL
        REFERENCES {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE}(id),
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    PRIMARY KEY(instruction_id, workflow_id)
);

CREATE TABLE IF NOT EXISTS {INSTRUCTION_PROJECTS_TABLE} (
    instruction_id INTEGER NOT NULL
        REFERENCES {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE}(id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    PRIMARY KEY(instruction_id, project_id)
);

CREATE INDEX IF NOT EXISTS idx_execution_instruction_workflows_workflow
    ON {INSTRUCTION_WORKFLOWS_TABLE}(workflow_id);
CREATE INDEX IF NOT EXISTS idx_execution_instruction_projects_project
    ON {INSTRUCTION_PROJECTS_TABLE}(project_id);
"""


def ensure_workflow_execution_instructions_schema(
    conn: Any, *, commit: bool = True
) -> None:
    """Create the instruction and scope-junction tables when absent."""
    execute_schema_script(conn, WORKFLOW_EXECUTION_INSTRUCTIONS_TABLES_SQL)
    if commit:
        conn.commit()
