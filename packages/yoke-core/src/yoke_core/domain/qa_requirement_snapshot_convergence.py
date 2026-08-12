"""Converge immutable execution metadata on QA requirements."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


SNAPSHOT_COLUMN_DEFINITIONS = (
    ("case_position", "INTEGER"),
    ("baseline_position", "INTEGER"),
    ("entry_surface", "TEXT"),
    ("required_completion", "TEXT"),
    ("method_name", "TEXT"),
    ("runner_id", "TEXT"),
    ("required_capability_kind", "TEXT"),
    ("verdict_path", "TEXT"),
)
SNAPSHOT_COLUMNS = tuple(column for column, _definition in SNAPSHOT_COLUMN_DEFINITIONS)

_REQUIRED_TABLES = (
    "qa_methods",
    "qa_plan_cases",
    "qa_requirements",
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _baseline_position(
    *,
    requirement_id: int,
    host_baseline: Any,
    raw_baselines: Any,
) -> int:
    try:
        baselines = json.loads(str(raw_baselines or "[]"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"QA requirement {requirement_id} has malformed plan baselines"
        ) from exc
    if not isinstance(baselines, list) or any(
        not isinstance(value, str) or not value for value in baselines
    ):
        raise RuntimeError(
            f"QA requirement {requirement_id} has invalid plan baselines"
        )
    if not baselines:
        if host_baseline is not None:
            raise RuntimeError(
                f"QA requirement {requirement_id} names an undeclared baseline"
            )
        return 1
    try:
        return baselines.index(str(host_baseline)) + 1
    except ValueError as exc:
        raise RuntimeError(
            f"QA requirement {requirement_id} names an undeclared baseline"
        ) from exc


def _snapshot_complete(row: Any) -> bool:
    method_complete = all(
        str(row[column] or "").strip()
        for column in ("method_name", "runner_id", "verdict_path")
    )
    if not method_complete:
        return False
    if row["plan_id"] is None:
        return True
    return row["case_position"] is not None and row["baseline_position"] is not None


def _backfill_rows(conn: Any) -> None:
    cursor = conn.execute(
        "SELECT q.id, q.plan_id, q.plan_case_key, q.method_id, "
        "q.host_baseline, q.case_position, q.baseline_position, "
        "q.entry_surface, q.required_completion, q.method_name, "
        "q.runner_id, q.required_capability_kind, q.verdict_path, "
        "c.position AS catalog_case_position, "
        "c.host_baselines AS catalog_host_baselines, "
        "c.entry_surface AS catalog_entry_surface, "
        "c.required_completion AS catalog_required_completion, "
        "m.name AS catalog_method_name, "
        "m.runner_id AS catalog_runner_id, "
        "m.required_capability_kind AS catalog_capability_kind, "
        "m.verdict_path AS catalog_verdict_path "
        "FROM qa_requirements q "
        "LEFT JOIN qa_plan_cases c "
        "ON c.plan_id=q.plan_id AND c.case_key=q.plan_case_key "
        "LEFT JOIN qa_methods m ON m.id=q.method_id "
        "WHERE q.method_id IS NOT NULL ORDER BY q.id",
    )
    columns = [
        str(getattr(column, "name", None) or column[0]) for column in cursor.description
    ]
    rows = [
        (
            {str(key): row[key] for key in row.keys()}
            if hasattr(row, "keys")
            else dict(zip(columns, row))
        )
        for row in cursor.fetchall()
    ]
    marker = _placeholder(conn)
    for row in rows:
        if _snapshot_complete(row):
            continue
        requirement_id = int(row["id"])
        if row["catalog_method_name"] is None:
            raise RuntimeError(
                f"QA requirement {requirement_id} has no registered method"
            )
        case_position = row["case_position"]
        baseline_position = row["baseline_position"]
        entry_surface = row["entry_surface"]
        required_completion = row["required_completion"]
        if row["plan_id"] is not None:
            if row["catalog_case_position"] is None:
                raise RuntimeError(
                    f"QA requirement {requirement_id} has no source plan case"
                )
            case_position = int(row["catalog_case_position"])
            baseline_position = _baseline_position(
                requirement_id=requirement_id,
                host_baseline=row["host_baseline"],
                raw_baselines=row["catalog_host_baselines"],
            )
            entry_surface = row["catalog_entry_surface"]
            required_completion = row["catalog_required_completion"]
        conn.execute(
            "UPDATE qa_requirements SET "
            f"case_position={marker}, baseline_position={marker}, "
            f"entry_surface={marker}, required_completion={marker}, "
            f"method_name={marker}, runner_id={marker}, "
            f"required_capability_kind={marker}, verdict_path={marker} "
            f"WHERE id={marker}",
            (
                case_position,
                baseline_position,
                entry_surface,
                required_completion,
                str(row["catalog_method_name"]),
                str(row["catalog_runner_id"]),
                row["catalog_capability_kind"],
                str(row["catalog_verdict_path"]),
                requirement_id,
            ),
        )


def converge_requirement_execution_snapshots(conn: Any) -> None:
    """Add and backfill snapshot fields without committing the caller's work."""
    missing = [table for table in _REQUIRED_TABLES if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "QA requirement snapshots require deployed catalog tables: "
            + ", ".join(missing)
        )
    for column, definition in SNAPSHOT_COLUMN_DEFINITIONS:
        _add_column_if_not_exists(conn, "qa_requirements", column, definition)
    _backfill_rows(conn)


def assert_requirement_execution_snapshot_invariants(conn: Any) -> None:
    """Require every method-backed row to carry its immutable runner fields."""
    missing_columns = [
        column
        for column in SNAPSHOT_COLUMNS
        if not _column_exists(conn, "qa_requirements", column)
    ]
    if missing_columns:
        raise AssertionError(
            "QA requirement snapshot columns are missing: " + ", ".join(missing_columns)
        )
    incomplete = int(
        conn.execute(
            "SELECT COUNT(*) FROM qa_requirements "
            "WHERE method_id IS NOT NULL AND ("
            "method_name IS NULL OR method_name='' OR "
            "runner_id IS NULL OR runner_id='' OR "
            "verdict_path IS NULL OR verdict_path='' OR "
            "(plan_id IS NOT NULL AND ("
            "case_position IS NULL OR case_position < 1 OR "
            "baseline_position IS NULL OR baseline_position < 1)))"
        ).fetchone()[0]
    )
    if incomplete:
        raise AssertionError(
            f"{incomplete} method-backed QA requirement snapshots are incomplete"
        )
    duplicate_positions = int(
        conn.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT item_id, deployment_run_id, workflow_transition_id, plan_id, "
            "case_position, baseline_position "
            "FROM qa_requirements WHERE plan_id IS NOT NULL "
            "GROUP BY item_id, deployment_run_id, workflow_transition_id, plan_id, "
            "case_position, baseline_position HAVING COUNT(*) > 1"
            ") duplicates"
        ).fetchone()[0]
    )
    if duplicate_positions:
        raise AssertionError(
            f"{duplicate_positions} QA requirement snapshot positions are duplicated"
        )


def converge_restored_requirement_snapshots(
    conn: Any,
    compatibility_error: type[Exception],
) -> None:
    """Converge restored rows and translate invalid snapshots for the loader."""
    try:
        converge_requirement_execution_snapshots(conn)
        assert_requirement_execution_snapshot_invariants(conn)
    except (AssertionError, RuntimeError) as exc:
        raise compatibility_error(
            "the restored universe has incompatible QA requirement snapshots"
        ) from exc


__all__ = [
    "SNAPSHOT_COLUMNS",
    "assert_requirement_execution_snapshot_invariants",
    "converge_requirement_execution_snapshots",
    "converge_restored_requirement_snapshots",
]
