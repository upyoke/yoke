"""Make an undecidable agent judgment explicit and explainable.

The old third verdict looked like a vague execution outcome. The current
verdict says exactly what the reviewer knows: the supplied evidence could
not establish pass or fail. Every such row now carries the reason why.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists


MINIMUM_SERVING_VERSION = "0.1.1+launch.245"
LEGACY_REASON = (
    "The original QA check could not establish pass or fail because its "
    "legacy verdict did not require a reason."
)


def _drop_verdict_checks(conn: Any, table: str) -> None:
    rows = conn.execute(
        "SELECT con.conname FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid=con.conrelid "
        "JOIN pg_namespace ns ON ns.oid=rel.relnamespace "
        "WHERE ns.nspname=current_schema() AND rel.relname=%s "
        "AND con.contype='c' AND pg_get_constraintdef(con.oid) ILIKE '%%verdict%%'",
        (table,),
    ).fetchall()
    for row in rows:
        name = str(row[0]).replace('"', '""')
        conn.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')


def _sqlite_accepts_current_verdict(conn: Any, table: str) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row and "undetermined" in str(row[0] or ""))


def apply(conn: Any) -> None:
    if not _table_exists(conn, "qa_runs"):
        return
    if not _column_exists(conn, "qa_runs", "verdict_reason"):
        conn.execute("ALTER TABLE qa_runs ADD COLUMN verdict_reason TEXT")
    postgres = db_backend.connection_is_postgres(conn)
    if not postgres and not _sqlite_accepts_current_verdict(conn, "qa_runs"):
        return

    from yoke_core.domain.schema_migrations import (
        _drop_qa_runs_verdict_trigger,
        _ensure_qa_runs_verdict_trigger,
        _qa_runs_verdict_trigger_exists,
    )

    trigger_present = _qa_runs_verdict_trigger_exists(conn)
    if trigger_present:
        _drop_qa_runs_verdict_trigger(conn)
    if postgres:
        _drop_verdict_checks(conn, "qa_runs")
        if _table_exists(conn, "qa_plan_review_verdicts"):
            _drop_verdict_checks(conn, "qa_plan_review_verdicts")
    conn.execute(
        "UPDATE qa_runs SET verdict='undetermined', "
        "verdict_reason=COALESCE(NULLIF(TRIM(verdict_reason), ''), %s) "
        "WHERE verdict='inconclusive'"
        if postgres
        else "UPDATE qa_runs SET verdict='undetermined', "
        "verdict_reason=COALESCE(NULLIF(TRIM(verdict_reason), ''), ?) "
        "WHERE verdict='inconclusive'",
        (LEGACY_REASON,),
    )
    if _table_exists(conn, "qa_plan_review_verdicts"):
        conn.execute(
            "UPDATE qa_plan_review_verdicts SET verdict='undetermined' "
            "WHERE verdict='inconclusive'"
        )
    if postgres:
        conn.execute(
            "ALTER TABLE qa_runs ADD CONSTRAINT qa_runs_verdict_check "
            "CHECK(verdict IN ('pass','fail','undetermined','error'))"
        )
        conn.execute(
            "ALTER TABLE qa_runs ADD CONSTRAINT qa_runs_undetermined_reason_check "
            "CHECK(verdict <> 'undetermined' OR "
            "COALESCE(LENGTH(TRIM(verdict_reason)), 0) > 0)"
        )
        if _table_exists(conn, "qa_plan_review_verdicts"):
            conn.execute(
                "ALTER TABLE qa_plan_review_verdicts ADD CONSTRAINT "
                "qa_plan_review_verdicts_verdict_check "
                "CHECK(verdict IN ('pass','fail','undetermined'))"
            )
    _ensure_qa_runs_verdict_trigger(conn)


def invariants(conn: Any) -> None:
    if not _table_exists(conn, "qa_runs"):
        return
    if not _column_exists(conn, "qa_runs", "verdict_reason"):
        raise AssertionError("qa_runs.verdict_reason is required")
    legacy = conn.execute(
        "SELECT COUNT(*) FROM qa_runs WHERE verdict='inconclusive'"
    ).fetchone()[0]
    unexplained = conn.execute(
        "SELECT COUNT(*) FROM qa_runs WHERE verdict='undetermined' "
        "AND NULLIF(TRIM(verdict_reason), '') IS NULL"
    ).fetchone()[0]
    if legacy or unexplained:
        raise AssertionError("QA verdicts are not fully explainable")
    if _table_exists(conn, "qa_plan_review_verdicts"):
        legacy_reviews = conn.execute(
            "SELECT COUNT(*) FROM qa_plan_review_verdicts WHERE verdict='inconclusive'"
        ).fetchone()[0]
        if legacy_reviews:
            raise AssertionError("QA plan review verdicts still use retired vocabulary")


__all__ = ["LEGACY_REASON", "MINIMUM_SERVING_VERSION", "apply", "invariants"]
