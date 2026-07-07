"""Path-target lookup helpers for boundary checks."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from yoke_core.domain import db_backend

PATH_TARGET_LOOKUP_BATCH_SIZE = 1000


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _chunks(target_ids: Sequence[int], batch_size: int):
    for offset in range(0, len(target_ids), batch_size):
        yield target_ids[offset: offset + batch_size]


def path_string_map_for_target_ids(
    conn: Any,
    target_ids: Sequence[int],
    *,
    batch_size: int = PATH_TARGET_LOOKUP_BATCH_SIZE,
) -> Dict[int, str]:
    """Return existing path-target strings keyed by target id."""
    if not target_ids:
        return {}
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    by_id: Dict[int, str] = {}
    for batch in _chunks([int(target_id) for target_id in target_ids], batch_size):
        placeholders = ", ".join(_p(conn) for _ in batch)
        rows = conn.execute(
            f"SELECT id, path_string FROM path_targets WHERE id IN ({placeholders})",
            tuple(batch),
        ).fetchall()
        for row in rows:
            by_id[int(row[0])] = str(row[1])
    return by_id


def path_strings_for_target_ids(
    conn: Any,
    target_ids: Sequence[int],
    *,
    batch_size: int = PATH_TARGET_LOOKUP_BATCH_SIZE,
) -> List[str]:
    """Return path strings for target ids, preserving declared order."""
    by_id = path_string_map_for_target_ids(
        conn, target_ids, batch_size=batch_size
    )

    return [
        by_id.get(int(target_id), f"<unknown target {int(target_id)}>")
        for target_id in target_ids
    ]


__all__ = ["path_string_map_for_target_ids", "path_strings_for_target_ids"]
