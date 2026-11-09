"""Validate immutable execution metadata on QA requirements."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import (
    _column_exists,
)
from yoke_core.domain.qa_method_capabilities import (
    QaMethodCapabilityError,
    capability_kinds,
)


SNAPSHOT_COLUMN_DEFINITIONS = (
    ("case_position", "INTEGER"),
    ("baseline_position", "INTEGER"),
    ("entry_surface", "TEXT"),
    ("required_completion", "TEXT"),
    ("method_name", "TEXT"),
    ("runner_id", "TEXT"),
    ("verdict_path", "TEXT"),
)
SNAPSHOT_COLUMNS = tuple(column for column, _definition in SNAPSHOT_COLUMN_DEFINITIONS)


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
            "capability_requirements IS NULL OR capability_requirements='' OR "
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
    for row in conn.execute(
        "SELECT id, capability_requirements FROM qa_requirements "
        "WHERE method_id IS NOT NULL"
    ).fetchall():
        requirement_id = int(row["id"] if hasattr(row, "keys") else row[0])
        raw_capabilities = (
            row["capability_requirements"] if hasattr(row, "keys") else row[1]
        )
        try:
            capability_kinds(
                raw_capabilities,
                subject=f"QA requirement {requirement_id}",
            )
        except QaMethodCapabilityError as exc:
            raise AssertionError(str(exc)) from exc
    standalone_owner = (
        "standalone_execution_id, "
        if _column_exists(conn, "qa_requirements", "standalone_execution_id")
        else ""
    )
    # A run holds one subject per stage, member and target: each plan group
    # of a plan has its own target, so two groups of one plan never collide.
    subject = (
        f"{standalone_owner}item_id, deployment_run_id, deployment_stage, "
        "deployment_member_item_id, execution_target_digest, workflow_transition_id, "
        "plan_id, case_position, baseline_position"
    )
    duplicate_positions = int(
        conn.execute(
            f"SELECT COUNT(*) FROM (SELECT {subject} FROM qa_requirements "
            f"WHERE plan_id IS NOT NULL GROUP BY {subject} HAVING COUNT(*) > 1"
            ") duplicates"
        ).fetchone()[0]
    )
    if duplicate_positions:
        raise AssertionError(
            f"{duplicate_positions} QA requirement snapshot positions are duplicated"
        )


def validate_restored_requirement_snapshots(
    conn: Any,
    compatibility_error: type[Exception],
) -> None:
    """Validate restored rows and translate invalid snapshots for the loader."""
    try:
        assert_requirement_execution_snapshot_invariants(conn)
    except (AssertionError, RuntimeError) as exc:
        raise compatibility_error(
            "the restored universe has incompatible QA requirement snapshots"
        ) from exc


__all__ = [
    "SNAPSHOT_COLUMNS",
    "assert_requirement_execution_snapshot_invariants",
    "validate_restored_requirement_snapshots",
]
