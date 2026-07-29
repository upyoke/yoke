"""Schema and code-owned definitions for QA methods and test plans."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


QA_CATALOG_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS qa_methods (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    source_kind TEXT NOT NULL
        CHECK(source_kind IN ('built_in','pack','project')),
    source_ref TEXT,
    project_id INTEGER REFERENCES projects(id),
    executor_id TEXT NOT NULL,
    required_capability_kind TEXT,
    verdict_path TEXT NOT NULL CHECK(verdict_path IN ('automatic','agent')),
    verdict_contract TEXT NOT NULL,
    evidence_contract TEXT NOT NULL,
    success_policy_id TEXT NOT NULL DEFAULT 'all-pass',
    success_policy_params TEXT NOT NULL DEFAULT '{}',
    concurrency_mode TEXT NOT NULL DEFAULT 'parallel'
        CHECK(concurrency_mode IN ('parallel','serial')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(
        (source_kind = 'project' AND project_id IS NOT NULL) OR
        (source_kind <> 'project' AND project_id IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS qa_plans (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    success_policy_id TEXT NOT NULL DEFAULT 'all-pass',
    success_policy_params TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    retired_at TEXT,
    target_environment_id TEXT REFERENCES environments(id),
    UNIQUE(project_id, slug)
);

CREATE TABLE IF NOT EXISTS qa_plan_cases (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES qa_plans(id),
    case_key TEXT NOT NULL,
    position INTEGER NOT NULL CHECK(position > 0),
    method_id TEXT NOT NULL REFERENCES qa_methods(id),
    instructions TEXT NOT NULL,
    expected_outcome TEXT NOT NULL,
    method_config TEXT NOT NULL DEFAULT '{}',
    success_policy_id TEXT,
    success_policy_params TEXT,
    host_baselines TEXT NOT NULL DEFAULT '[]',
    entry_surface TEXT,
    required_completion TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(plan_id, case_key),
    UNIQUE(plan_id, position)
);

CREATE TABLE IF NOT EXISTS qa_plan_project_defaults (
    project_id INTEGER NOT NULL REFERENCES projects(id),
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    transition_id TEXT NOT NULL,
    qa_phase TEXT NOT NULL DEFAULT 'verification'
        CHECK(qa_phase IN ('verification','post_deploy','manual_acceptance')),
    plan_id INTEGER NOT NULL REFERENCES qa_plans(id),
    attached_at TEXT NOT NULL,
    attached_by_actor_id INTEGER,
    PRIMARY KEY(project_id, workflow_id, transition_id, plan_id)
);

CREATE TABLE IF NOT EXISTS qa_plan_item_attachments (
    item_id INTEGER NOT NULL REFERENCES items(id),
    transition_id TEXT NOT NULL,
    qa_phase TEXT NOT NULL DEFAULT 'verification'
        CHECK(qa_phase IN ('verification','post_deploy','manual_acceptance')),
    plan_id INTEGER NOT NULL REFERENCES qa_plans(id),
    attached_at TEXT NOT NULL,
    attached_by_actor_id INTEGER,
    PRIMARY KEY(item_id, transition_id, plan_id)
);

CREATE INDEX IF NOT EXISTS idx_qa_plans_project
    ON qa_plans(project_id, retired_at, slug);
CREATE INDEX IF NOT EXISTS idx_qa_plan_cases_plan
    ON qa_plan_cases(plan_id, position);
CREATE INDEX IF NOT EXISTS idx_qa_project_defaults_plan
    ON qa_plan_project_defaults(plan_id);
CREATE INDEX IF NOT EXISTS idx_qa_item_attachments_plan
    ON qa_plan_item_attachments(plan_id);
"""

BUILTIN_QA_METHODS = (
    {
        "id": "command",
        "name": "Command",
        "description": (
            "Run the project's deterministic commands in a worktree — "
            "exit 0 is the verdict, captured output is the evidence."
        ),
        "executor_id": "worktree_run",
        "required_capability_kind": None,
        "verdict_path": "automatic",
        "verdict_contract": "exit 0 = pass",
        "evidence_contract": "exit code · captured output tail",
    },
    {
        "id": "browser-check",
        "name": "Browser check",
        "description": (
            "Playwright-style assertions against declared routes; automatic verdict."
        ),
        "executor_id": "browser_substrate",
        "required_capability_kind": "browser-control",
        "verdict_path": "automatic",
        "verdict_contract": "assertions",
        "evidence_contract": "assertions · trace · logs",
    },
    {
        "id": "browser-inspection",
        "name": "Browser inspection",
        "description": (
            "Captures screenshots; an agent judges whether they show the "
            "case's expected outcome."
        ),
        "executor_id": "browser_substrate",
        "required_capability_kind": "browser-control",
        "verdict_path": "agent",
        "verdict_contract": (
            "inspects the screenshot and judges whether it shows the case's "
            "expected outcome"
        ),
        "evidence_contract": "screenshots · inspection verdict",
    },
)

_REQUIREMENT_COLUMNS = (
    ("plan_id", "INTEGER REFERENCES qa_plans(id)"),
    ("plan_case_key", "TEXT"),
    ("case_position", "INTEGER"),
    ("baseline_position", "INTEGER"),
    ("method_id", "TEXT REFERENCES qa_methods(id)"),
    ("method_name", "TEXT"),
    ("executor_id", "TEXT"),
    ("required_capability_kind", "TEXT"),
    ("verdict_path", "TEXT"),
    ("host_baseline", "TEXT"),
    ("entry_surface", "TEXT"),
    ("required_completion", "TEXT"),
    ("workflow_transition_id", "TEXT"),
    ("instructions", "TEXT"),
    ("expected_outcome", "TEXT"),
    ("method_config", "TEXT"),
    ("execution_target_json", "TEXT"),
    ("execution_target_digest", "TEXT"),
)

_RUN_COLUMNS = (
    (
        "case_outcome",
        "TEXT CHECK(case_outcome IN "
        "('running','waiting','passed','failed','needs_review',"
        "'blocked_on_precondition'))",
    ),
    ("capture_degraded_reason", "TEXT"),
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_builtin_methods(conn: Any) -> None:
    marker = _placeholder(conn)
    now = iso8601_now()
    columns = (
        "id",
        "name",
        "description",
        "source_kind",
        "source_ref",
        "project_id",
        "executor_id",
        "required_capability_kind",
        "verdict_path",
        "verdict_contract",
        "evidence_contract",
        "success_policy_id",
        "success_policy_params",
        "concurrency_mode",
        "created_at",
        "updated_at",
    )
    values = ", ".join([marker] * len(columns))
    assignments = ", ".join(
        f"{column}=EXCLUDED.{column}"
        for column in columns
        if column not in {"id", "created_at"}
    )
    sql = (
        f"INSERT INTO qa_methods ({', '.join(columns)}) VALUES ({values}) "
        f"ON CONFLICT(id) DO UPDATE SET {assignments}"
    )
    for method in BUILTIN_QA_METHODS:
        conn.execute(
            sql,
            (
                method["id"],
                method["name"],
                method["description"],
                "built_in",
                None,
                None,
                method["executor_id"],
                method["required_capability_kind"],
                method["verdict_path"],
                method["verdict_contract"],
                method["evidence_contract"],
                "all-pass",
                json.dumps({}, sort_keys=True),
                "parallel",
                now,
                now,
            ),
        )


def create_qa_catalog_tables(conn: Any) -> None:
    """Converge the additive QA catalog and seed the core method roster."""
    execute_schema_script(conn, QA_CATALOG_TABLES_SQL)
    _add_column_if_not_exists(
        conn,
        "qa_plans",
        "target_environment_id",
        "TEXT REFERENCES environments(id)",
    )
    for column, definition in _REQUIREMENT_COLUMNS:
        _add_column_if_not_exists(conn, "qa_requirements", column, definition)
    for column, definition in _RUN_COLUMNS:
        _add_column_if_not_exists(conn, "qa_runs", column, definition)
    for table in (
        "qa_plan_project_defaults",
        "qa_plan_item_attachments",
    ):
        _add_column_if_not_exists(
            conn,
            table,
            "qa_phase",
            "TEXT NOT NULL DEFAULT 'verification' "
            "CHECK(qa_phase IN "
            "('verification','post_deploy','manual_acceptance'))",
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "idx_qa_requirement_materialization "
        "ON qa_requirements("
        "item_id, plan_id, plan_case_key, "
        "COALESCE(host_baseline, ''), workflow_transition_id"
        ") WHERE item_id IS NOT NULL AND plan_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "idx_qa_requirement_deployment_materialization "
        "ON qa_requirements("
        "deployment_run_id, plan_id, plan_case_key, "
        "COALESCE(host_baseline, '')"
        ") WHERE deployment_run_id IS NOT NULL AND plan_id IS NOT NULL"
    )
    _seed_builtin_methods(conn)
    conn.commit()


__all__ = [
    "BUILTIN_QA_METHODS",
    "QA_CATALOG_TABLES_SQL",
    "create_qa_catalog_tables",
]
