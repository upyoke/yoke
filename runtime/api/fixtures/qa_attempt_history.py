"""Actual-attempt read substrate for deliberately narrow QA test databases.

These native PostgreSQL fixtures never run plan executions. They still need
the durable judgment association so real readers cannot classify runs from
runner labels.
No execution or evidence is seeded by this schema helper.
"""

from typing import Any
from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


def ensure_qa_attempt_history(conn: Any) -> None:
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS qa_plan_review_verdicts (
            bundle_id TEXT,
            requirement_id INTEGER,
            capture_run_id INTEGER,
            review_run_id INTEGER,
            verdict TEXT,
            rationale TEXT,
            decision_request_id INTEGER,
            created_at TIMESTAMPTZ
        );
    """,
    )
    for column, kind in (
        ("started_at", "TIMESTAMPTZ"),
        ("completed_at", "TIMESTAMPTZ"),
        ("raw_result", "TEXT"),
        ("verdict_reason", "TEXT"),
        ("case_outcome", "TEXT"),
    ):
        _add_column_if_not_exists(conn, "qa_runs", column, kind)
    for column, kind in (
        ("superseded_by_requirement_id", "INTEGER"),
        ("replacement_requirement_id", "INTEGER"),
        ("retracted_at", "TIMESTAMPTZ"),
    ):
        _add_column_if_not_exists(conn, "qa_requirements", column, kind)
