"""Drop obsolete scalar columns from the items table."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migrations.obsolete_schema_cleanup import (
    apply_item_columns,
    verify_item_columns,
)

MIGRATION_NAME = "drop_obsolete_item_columns"


def apply(conn: Any) -> None:
    apply_item_columns(conn)


def invariants(conn: Any) -> None:
    verify_item_columns(conn)


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
