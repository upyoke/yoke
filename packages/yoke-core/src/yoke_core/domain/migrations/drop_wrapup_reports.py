"""Drop the retired session-report table wherever an install still holds it."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migrations.obsolete_schema_cleanup import (
    apply_wrapup_reports_drop,
    verify_wrapup_reports_drop,
)

MIGRATION_NAME = "drop_wrapup_reports"


def apply(conn: Any) -> None:
    apply_wrapup_reports_drop(conn)


def invariants(conn: Any) -> None:
    verify_wrapup_reports_drop(conn)


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
