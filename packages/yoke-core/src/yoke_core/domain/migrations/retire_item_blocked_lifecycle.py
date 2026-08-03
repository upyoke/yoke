"""Retire the stale item-level blocked lifecycle residue."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migrations.obsolete_schema_cleanup import (
    apply_item_blocked_lifecycle,
    verify_item_blocked_lifecycle,
)

MIGRATION_NAME = "retire_item_blocked_lifecycle"


def apply(conn: Any) -> None:
    apply_item_blocked_lifecycle(conn)


def invariants(conn: Any) -> None:
    verify_item_blocked_lifecycle(conn)


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
