"""Schema migration helpers for the Yoke authority DB.

Verdict evidence invariants shared by initialization and permanent history.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common_sqlite_validation import (
    _generic_sqlite_validation_trigger_exists,
)


def _row_value(row: Any, key: str, index: int) -> Any:
    if hasattr(row, "keys"):
        return row[key]
    return row[index]


# Shared by initial schema creation and permanent migration history.
QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME = "qa_runs_verdict_immutable"

QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_SQL = (
    f"CREATE TRIGGER IF NOT EXISTS {QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME}\n"
    "BEFORE UPDATE OF verdict, verdict_reason, raw_result ON qa_runs\n"
    "WHEN OLD.verdict IS NOT NULL\n"
    "BEGIN\n"
    "  SELECT RAISE(ABORT,\n"
    "    'qa_runs.verdict, verdict_reason, and raw_result are immutable once verdict is set; "
    "final verdicts require a new actual attempt; provisional undetermined requires its resolved decision request');\n"
    "END"
)


_PG_QA_RUNS_VERDICT_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION qa_runs_verdict_immutable_fn()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.verdict IS NULL OR (
       NEW.verdict IS NOT DISTINCT FROM OLD.verdict
       AND NEW.verdict_reason IS NOT DISTINCT FROM OLD.verdict_reason
       AND NEW.raw_result IS NOT DISTINCT FROM OLD.raw_result
     ) THEN
    RETURN NEW;
  END IF;
  IF OLD.verdict = 'undetermined' AND NEW.verdict IN ('pass','fail')
       AND NEW.raw_result IS NOT DISTINCT FROM OLD.raw_result
       AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at THEN
    IF EXISTS (
         SELECT 1 FROM decision_requests request
         WHERE request.kind='qa_needs_review' AND request.status='resolved'
           AND request.subject_type='qa_requirement'
           AND request.subject_key=OLD.qa_requirement_id::text
           AND (request.subject_context::jsonb->>'run_id')=OLD.id::text
           AND request.resolution_actor_id IS NOT NULL AND request.resolved_at IS NOT NULL
           AND request.resolution_action=CASE NEW.verdict WHEN 'pass' THEN 'approve' ELSE 'reject' END
           AND NEW.verdict_reason IS NOT DISTINCT FROM COALESCE(request.resolution_note,'')
       ) THEN
      RETURN NEW;
    END IF;
  END IF;
  RAISE EXCEPTION 'qa_runs.verdict, verdict_reason, and raw_result are immutable once verdict is set; final verdicts require a new actual attempt; provisional undetermined requires its resolved decision request';
END;
$$;
"""

_PG_QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_SQL = f"""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_trigger
    WHERE tgname = '{QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME}'
      AND NOT tgisinternal
  ) THEN
    CREATE TRIGGER {QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME}
    BEFORE UPDATE OF verdict, verdict_reason, raw_result ON qa_runs
    FOR EACH ROW
    EXECUTE FUNCTION qa_runs_verdict_immutable_fn();
  END IF;
END
$$;
"""


def _ensure_qa_runs_verdict_trigger(conn: Any) -> None:
    """Install immutable verdict, reason, and raw-result evidence."""
    if db_backend.connection_is_postgres(conn):
        conn.execute(_PG_QA_RUNS_VERDICT_IMMUTABLE_FUNCTION_SQL)
        conn.execute(_PG_QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_SQL)
        return
    conn.execute(QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_SQL)


def _qa_runs_verdict_trigger_exists(conn: Any) -> bool:
    if db_backend.connection_is_postgres(conn):
        row = conn.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_trigger trig
                JOIN pg_catalog.pg_class cls ON cls.oid = trig.tgrelid
                JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
                WHERE ns.nspname = current_schema()
                  AND cls.relname = 'qa_runs'
                  AND trig.tgname = %s
                  AND NOT trig.tgisinternal
            )
            """,
            (QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME,),
        ).fetchone()
        return bool(row and _row_value(row, "exists", 0))
    return _generic_sqlite_validation_qa_runs_verdict_trigger_exists(conn)


def _generic_sqlite_validation_qa_runs_verdict_trigger_exists(conn: Any) -> bool:
    """Return trigger presence for non-authority SQLite validation DBs."""
    return _generic_sqlite_validation_trigger_exists(
        conn,
        QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME,
    )


def _drop_qa_runs_verdict_trigger(conn: Any) -> None:
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            f"DROP TRIGGER IF EXISTS {QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME} "
            "ON qa_runs"
        )
        return
    conn.execute(f"DROP TRIGGER {QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME}")
