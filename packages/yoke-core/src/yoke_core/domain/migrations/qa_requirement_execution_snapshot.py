"""Govern immutable executor metadata on existing QA requirements."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_requirement_snapshot_convergence import (
    SNAPSHOT_COLUMNS,
    assert_requirement_execution_snapshot_invariants,
    converge_requirement_execution_snapshots,
)


MIGRATION_NAME = "qa_requirement_execution_snapshot"


def apply(conn: Any) -> None:
    """Converge only the declared requirement snapshot fields and their data."""
    converge_requirement_execution_snapshots(conn)


def invariants(conn: Any) -> None:
    """Require every method-backed row to carry its immutable executor fields."""
    assert_requirement_execution_snapshot_invariants(conn)


__all__ = [
    "MIGRATION_NAME",
    "SNAPSHOT_COLUMNS",
    "apply",
    "invariants",
]
