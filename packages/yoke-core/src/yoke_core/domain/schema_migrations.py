"""Schema migration helpers for the Yoke authority DB.

Idempotent data-shape migrations applied during schema init. Callers import
these through schema.py.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.schema_common_sqlite_validation import (
    _generic_sqlite_validation_trigger_exists,
)


def _row_value(row: Any, key: str, index: int) -> Any:
    if hasattr(row, "keys"):
        return row[key]
    return row[index]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# Single source of truth for the qa_runs verdict-immutability trigger.
# Used by ``_migrate_qa_execution_status`` during ``schema.cmd_init``
# (fresh-DB install), by the governed migration module (apply on existing
# DBs), and by the one-shot browser capture re-partition that legitimately
# mutates verdict.
QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME = "qa_runs_verdict_immutable"

QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_SQL = (
    f"CREATE TRIGGER IF NOT EXISTS {QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME}\n"
    "BEFORE UPDATE OF verdict, raw_result ON qa_runs\n"
    "WHEN OLD.verdict IS NOT NULL\n"
    "BEGIN\n"
    "  SELECT RAISE(ABORT,\n"
    "    'qa_runs.verdict and raw_result are immutable once verdict is set; "
    "record a new run via qa run-add');\n"
    "END"
)


_PG_QA_RUNS_VERDICT_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION qa_runs_verdict_immutable_fn()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.verdict IS NOT NULL
     AND (
       NEW.verdict IS DISTINCT FROM OLD.verdict
       OR NEW.raw_result IS DISTINCT FROM OLD.raw_result
     ) THEN
    RAISE EXCEPTION 'qa_runs.verdict and raw_result are immutable once verdict is set; record a new run via qa run-add';
  END IF;
  RETURN NEW;
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
    BEFORE UPDATE OF verdict, raw_result ON qa_runs
    FOR EACH ROW
    EXECUTE FUNCTION qa_runs_verdict_immutable_fn();
  END IF;
END
$$;
"""


def _ensure_qa_runs_verdict_trigger(conn: Any) -> None:
    """Install the qa_runs verdict/raw_result immutability trigger."""
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


def _migrate_qa_execution_status(conn: Any) -> None:
    """Split infrastructure capture from quality verdict on qa_runs.

    Adds the ``execution_status`` column to ``qa_runs`` and
    partitions existing ``browser_smoke`` / ``browser_diff`` rows:

    - ``verdict='fail'`` → ``execution_status='capture_failed'``; verdict preserved
      (fail rows already carry the right quality signal).
    - ``verdict='pass'`` AND sibling ``ac_verification`` pass exists on the same
      item with ``requires_screenshot_evidence`` in its ``success_policy`` →
      ``execution_status='captured'``; verdict preserved (inspection already
      already happened under the current evidence model).
    - ``verdict='pass'`` without inspection evidence →
      ``execution_status='captured'`` and ``verdict=NULL`` to force re-inspection
      on next touch. Infrastructure success alone no longer satisfies any
      ``verdict='pass'`` gate.

    Non-browser rows (ac_verification, implementation_review, e2e, etc.)
    keep ``execution_status=NULL``.
    """
    if not _table_exists(conn, "qa_runs"):
        return

    if _column_exists(conn, "qa_runs", "execution_status"):
        _ensure_qa_runs_verdict_trigger(conn)
        conn.commit()
        return

    conn.execute(
        "ALTER TABLE qa_runs ADD COLUMN execution_status TEXT "
        "CHECK(execution_status IN ('captured','capture_failed') "
        "OR execution_status IS NULL)"
    )

    conn.execute(
        "UPDATE qa_runs SET execution_status='capture_failed' "
        "WHERE qa_kind IN ('browser_smoke','browser_diff') AND verdict='fail'"
    )

    p = _p(conn)
    conn.execute(
        f"""
        UPDATE qa_runs SET execution_status='captured'
        WHERE qa_kind IN ('browser_smoke','browser_diff')
          AND verdict='pass'
          AND qa_requirement_id IN (
            SELECT qr_browser.id FROM qa_requirements qr_browser
            WHERE qr_browser.qa_kind IN ('browser_smoke','browser_diff')
              AND EXISTS (
                SELECT 1 FROM qa_requirements qr_ac
                JOIN qa_runs run_ac ON run_ac.qa_requirement_id = qr_ac.id
                WHERE qr_ac.item_id = qr_browser.item_id
                  AND qr_ac.qa_kind = 'ac_verification'
                  -- deliberate case-sensitive match against internal success_policy token
                  AND qr_ac.success_policy LIKE {p}
                  AND run_ac.verdict = 'pass'
                  AND run_ac.executor_type = 'browser_substrate'
              )
          )
        """,
        ("%requires_screenshot_evidence%",),
    )

    # The next UPDATE flips verdict='pass' -> verdict=NULL for browser
    # capture rows that never had inspection evidence. The
    # qa_runs_verdict_immutable trigger refuses post-completion verdict
    # writes by design; this one-shot browser capture re-partition must
    # be allowed to run on older DBs. Drop the
    # trigger for the duration of the UPDATE and recreate it from the
    # canonical SQL constant immediately after.
    trigger_present = _qa_runs_verdict_trigger_exists(conn)
    if trigger_present:
        _drop_qa_runs_verdict_trigger(conn)

    try:
        conn.execute(
            """
            UPDATE qa_runs SET execution_status='captured', verdict=NULL
            WHERE qa_kind IN ('browser_smoke','browser_diff')
              AND verdict='pass'
              AND execution_status IS NULL
            """
        )
    finally:
        if trigger_present:
            _ensure_qa_runs_verdict_trigger(conn)

    _ensure_qa_runs_verdict_trigger(conn)
    conn.commit()
