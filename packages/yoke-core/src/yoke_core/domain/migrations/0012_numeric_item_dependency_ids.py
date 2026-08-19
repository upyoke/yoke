"""Store item_dependencies endpoints as integer foreign keys to items.id.

The live columns held public PREFIX-N text. That shape let a well-formed
string name the wrong item once project_sequence diverged from items.id,
and it forbade a foreign key. Unresolved strings (orphans) cannot become
integers; this entry reports each one and drops it.

Public PREFIX-N remains the API and display token. Storage is
dependent_item_id / blocking_item_id.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migrations._numeric_item_dependency_ids import (
    rebuild_registry,
    registry_is_numeric,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


MINIMUM_SERVING_VERSION = "0.1.1+launch.239"


def apply(conn: Any) -> None:
    rebuild_registry(conn)


def invariants(conn: Any) -> None:
    if not _table_exists(conn, "item_dependencies"):
        return
    if not registry_is_numeric(conn):
        raise AssertionError(
            "item_dependencies endpoints are not numeric item ids"
        )
    if _column_exists(conn, "item_dependencies", "dependent_item"):
        raise AssertionError(
            "item_dependencies.dependent_item is retired but still present"
        )
    if _column_exists(conn, "item_dependencies", "blocking_item"):
        raise AssertionError(
            "item_dependencies.blocking_item is retired but still present"
        )
    dangling = conn.execute(
        "SELECT d.id FROM item_dependencies d "
        "LEFT JOIN items dep ON dep.id = d.dependent_item_id "
        "LEFT JOIN items blk ON blk.id = d.blocking_item_id "
        "WHERE dep.id IS NULL OR blk.id IS NULL"
    ).fetchall()
    if dangling:
        raise AssertionError("item_dependencies has dangling item references")


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
