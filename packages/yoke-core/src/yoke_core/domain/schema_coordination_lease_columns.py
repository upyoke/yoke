"""Additive typed-owner columns for ``coordination_leases``."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists


def apply_coordination_lease_columns(conn: Any) -> None:
    """Add typed-owner and release-provenance columns on existing universes."""
    for column, ddl in (
        ("owner_kind", "TEXT NOT NULL DEFAULT 'session'"),
        ("owner_item_id", "INTEGER DEFAULT NULL"),
        ("owner_session_id", "TEXT DEFAULT NULL"),
        ("owner_work_claim_id", "INTEGER DEFAULT NULL"),
        ("released_by_session_id", "TEXT DEFAULT NULL"),
        ("released_by_actor_id", "TEXT DEFAULT NULL"),
    ):
        _add_column_if_not_exists(conn, "coordination_leases", column, ddl)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coordination_leases_owner_item "
        "ON coordination_leases(owner_item_id)"
    )
    conn.commit()


__all__ = ["apply_coordination_lease_columns"]
