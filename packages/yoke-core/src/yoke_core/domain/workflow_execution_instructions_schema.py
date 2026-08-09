"""Schema for operator-authored workflow execution instructions.

An instruction is a block of operator prose that agents must obey when
executing items. Scope is declarative on two axes, each with the same
shape: an ``applies_to_all_*`` predicate, or explicit junction rows.
Membership is resolved at read time — neither predicate is ever
materialized into rows, so a new workflow or project is covered
automatically by an instruction that claims all of them.

The prose is the whole instruction. There is no title to keep in step with
it, no ordering to maintain by hand, and no status: an instruction that
should not apply is unscoped or deleted, which cannot drift from what the
agent actually reads.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE = "workflow_execution_instructions"
INSTRUCTION_WORKFLOWS_TABLE = "workflow_execution_instruction_workflows"
INSTRUCTION_PROJECTS_TABLE = "workflow_execution_instruction_projects"

WORKFLOW_EXECUTION_INSTRUCTIONS_TABLES_SQL = f"""
CREATE TABLE IF NOT EXISTS {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} (
    id INTEGER PRIMARY KEY,
    content TEXT NOT NULL,
    applies_to_all_workflows INTEGER NOT NULL DEFAULT 0,
    applies_to_all_projects INTEGER NOT NULL DEFAULT 0,
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
    # The workflow axis gained the same all-of-them predicate the project axis
    # already had. Additive, so it reaches an existing universe on its next
    # boot rather than through the migration history.
    _add_column_if_not_exists(
        conn,
        WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE,
        "applies_to_all_workflows",
        "INTEGER NOT NULL DEFAULT 0",
    )
    if commit:
        conn.commit()
