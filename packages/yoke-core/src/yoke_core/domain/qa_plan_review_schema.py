"""Durable authority for one batched agent review per QA plan execution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import (
    _column_exists,
    _index_exists,
    _table_exists,
)
from yoke_core.domain.schema_init_apply import execute_schema_script


QA_PLAN_REVIEW_BUNDLE_TABLE = "qa_plan_review_bundles"
QA_PLAN_REVIEW_VERDICT_TABLE = "qa_plan_review_verdicts"

QA_PLAN_REVIEW_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS qa_plan_review_bundles (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE REFERENCES qa_plan_executions(id),
    roster_digest TEXT NOT NULL,
    bundle_digest TEXT NOT NULL,
    bundle_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','completed')),
    reviewer_actor_id TEXT,
    reviewer_session_id TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_plan_review_bundles_execution
    ON qa_plan_review_bundles(execution_id);

CREATE TABLE IF NOT EXISTS qa_plan_review_verdicts (
    bundle_id TEXT NOT NULL REFERENCES qa_plan_review_bundles(id),
    requirement_id INTEGER NOT NULL REFERENCES qa_requirements(id),
    capture_run_id INTEGER NOT NULL REFERENCES qa_runs(id),
    review_run_id INTEGER NOT NULL REFERENCES qa_runs(id),
    verdict TEXT NOT NULL CHECK(verdict IN ('pass','fail','undetermined')),
    rationale TEXT NOT NULL,
    decision_request_id INTEGER,
    created_at TEXT NOT NULL,
    PRIMARY KEY(bundle_id, requirement_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_plan_review_verdicts_run
    ON qa_plan_review_verdicts(review_run_id);
"""

_TABLE_COLUMNS = {
    QA_PLAN_REVIEW_BUNDLE_TABLE: (
        "id",
        "execution_id",
        "roster_digest",
        "bundle_digest",
        "bundle_json",
        "state",
        "reviewer_actor_id",
        "reviewer_session_id",
        "created_at",
        "reviewed_at",
    ),
    QA_PLAN_REVIEW_VERDICT_TABLE: (
        "bundle_id",
        "requirement_id",
        "capture_run_id",
        "review_run_id",
        "verdict",
        "rationale",
        "decision_request_id",
        "created_at",
    ),
}


def ensure_qa_plan_review_schema(conn: Any) -> None:
    """Create the additive batch-review tables without committing the caller."""
    execute_schema_script(conn, QA_PLAN_REVIEW_SCHEMA_SQL)


def assert_qa_plan_review_schema(conn: Any) -> None:
    """Require the complete bundle/verdict authority and lookup indexes."""
    missing_tables = [
        table for table in _TABLE_COLUMNS if not _table_exists(conn, table)
    ]
    if missing_tables:
        raise AssertionError(
            "QA plan review tables are missing: " + ", ".join(missing_tables)
        )
    missing_columns = [
        f"{table}.{column}"
        for table, columns in _TABLE_COLUMNS.items()
        for column in columns
        if not _column_exists(conn, table, column)
    ]
    if missing_columns:
        raise AssertionError(
            "QA plan review columns are missing: " + ", ".join(missing_columns)
        )
    missing_indexes = [
        name
        for table, name in (
            (
                QA_PLAN_REVIEW_BUNDLE_TABLE,
                "idx_qa_plan_review_bundles_execution",
            ),
            (
                QA_PLAN_REVIEW_VERDICT_TABLE,
                "idx_qa_plan_review_verdicts_run",
            ),
        )
        if not _index_exists(conn, name, table)
    ]
    if missing_indexes:
        raise AssertionError(
            "QA plan review indexes are missing: " + ", ".join(missing_indexes)
        )


__all__ = [
    "QA_PLAN_REVIEW_BUNDLE_TABLE",
    "QA_PLAN_REVIEW_SCHEMA_SQL",
    "QA_PLAN_REVIEW_VERDICT_TABLE",
    "assert_qa_plan_review_schema",
    "ensure_qa_plan_review_schema",
]
