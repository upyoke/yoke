"""Drop the unused scalar dependency column from epic tasks."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migrations.obsolete_schema_cleanup import (
    apply_epic_task_blocked_by,
    verify_epic_task_blocked_by,
)

MIGRATION_NAME = "drop_epic_task_blocked_by"


def apply(conn: Any) -> None:
    apply_epic_task_blocked_by(conn)


def invariants(conn: Any) -> None:
    verify_epic_task_blocked_by(conn)


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
