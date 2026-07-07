"""Snapshot-scoped context inheritance cache."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.path_context import (
    FAMILY_GENERATED,
    FAMILY_POSTURE,
)
from yoke_core.domain.path_registry import _parent_path_string


_QUERY_CHUNK_SIZE = 500


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _chunks(values: Sequence[Any]) -> Iterable[Sequence[Any]]:
    for idx in range(0, len(values), _QUERY_CHUNK_SIZE):
        yield values[idx: idx + _QUERY_CHUNK_SIZE]


def _get(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


@dataclass(frozen=True)
class SnapshotContextCache:
    parent_ids: Dict[int, Optional[int]]
    values: Dict[Tuple[int, str, str], str]

    def read_context_value(
        self,
        *,
        target_id: int,
        context_family: str,
        entry_key: str,
    ) -> Optional[Dict[str, Any]]:
        current: Optional[int] = target_id
        while current is not None:
            value_text = self.values.get((current, context_family, entry_key))
            if value_text is not None:
                try:
                    return json.loads(value_text or "{}")
                except (TypeError, ValueError):
                    return {}
            current = self.parent_ids.get(current)
        return None

    def area_for(self, target_id: int) -> Optional[str]:
        value = self.read_context_value(
            target_id=target_id,
            context_family=FAMILY_POSTURE,
            entry_key="area",
        )
        if value is None:
            return None
        area = value.get("area") if isinstance(value, dict) else None
        if isinstance(area, str) and area.strip():
            return area
        return None

    def is_generated(self, target_id: int) -> int:
        value = self.read_context_value(
            target_id=target_id,
            context_family=FAMILY_GENERATED,
            entry_key="",
        )
        return 1 if isinstance(value, dict) and value else 0


def build_snapshot_context_cache(
    conn: Any,
    *,
    targets: Sequence[Tuple[str, str]],
    target_ids: Dict[str, int],
) -> SnapshotContextCache:
    parent_ids: Dict[int, Optional[int]] = {}
    for path_string, _kind in targets:
        parent = _parent_path_string(path_string)
        target_id = target_ids[path_string]
        parent_ids[target_id] = None if parent is None else target_ids[parent]
    values: Dict[Tuple[int, str, str], str] = {}
    ids = list(parent_ids)
    if not ids:
        return SnapshotContextCache(parent_ids=parent_ids, values=values)
    p = _p(conn)
    for chunk in _chunks(ids):
        placeholders = ",".join(p for _ in chunk)
        rows = conn.execute(
            "SELECT target_id, context_family, entry_key, value "
            "FROM path_context_values "
            f"WHERE target_id IN ({placeholders})",
            tuple(chunk),
        ).fetchall()
        for row in rows:
            values[
                (
                    int(_get(row, "target_id", 0)),
                    str(_get(row, "context_family", 1)),
                    str(_get(row, "entry_key", 2)),
                )
            ] = str(_get(row, "value", 3) or "")
    return SnapshotContextCache(parent_ids=parent_ids, values=values)


__all__ = ["SnapshotContextCache", "build_snapshot_context_cache"]
