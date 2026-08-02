"""Drop the unused parent-id column from the event ledger."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migrations.obsolete_schema_cleanup import (
    apply_event_parent_id,
    verify_event_parent_id,
)

MIGRATION_NAME = "drop_event_parent_id"


def apply(conn: Any) -> None:
    apply_event_parent_id(conn)


def invariants(conn: Any) -> None:
    verify_event_parent_id(conn)


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
