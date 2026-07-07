"""Bulk target resolution for path-snapshot materialization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.path_registry import _mint_target, _parent_path_string
from yoke_core.domain.path_targets_states import PRE_OBSERVATION_STATES


_QUERY_CHUNK_SIZE = 500


@dataclass(frozen=True)
class LatestTarget:
    id: int
    path_string: str
    generation: int
    kind: str
    parent_target_id: Optional[int]
    materialization_state: str


@dataclass(frozen=True)
class SnapshotTargetResolution:
    target_ids: Dict[str, int]
    materialize_target_ids: List[int]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _chunks(values: Sequence[Any]) -> Iterable[Sequence[Any]]:
    for idx in range(0, len(values), _QUERY_CHUNK_SIZE):
        yield values[idx: idx + _QUERY_CHUNK_SIZE]


def _get(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _latest_targets_by_path(
    conn: Any,
    *,
    project_id: int,
    path_strings: Sequence[str],
) -> Dict[str, LatestTarget]:
    latest: Dict[str, LatestTarget] = {}
    unique_paths = list(dict.fromkeys(path_strings))
    if not unique_paths:
        return latest
    p = _p(conn)
    for chunk in _chunks(unique_paths):
        placeholders = ",".join(p for _ in chunk)
        rows = conn.execute(
            "SELECT id, path_string, generation, kind, parent_target_id, "
            "       COALESCE(materialization_state, 'observed') "
            "       AS materialization_state "
            "FROM path_targets "
            f"WHERE project_id = {p} AND path_string IN ({placeholders}) "
            "ORDER BY path_string ASC, generation DESC",
            (project_id, *chunk),
        ).fetchall()
        for row in rows:
            path_string = str(_get(row, "path_string", 1))
            if path_string in latest:
                continue
            parent = _get(row, "parent_target_id", 4)
            latest[path_string] = LatestTarget(
                id=int(_get(row, "id", 0)),
                path_string=path_string,
                generation=int(_get(row, "generation", 2)),
                kind=str(_get(row, "kind", 3)),
                parent_target_id=None if parent is None else int(parent),
                materialization_state=str(
                    _get(row, "materialization_state", 5)
                ),
            )
    return latest


def _targets_with_observed_disappearance(
    conn: Any,
    *,
    project_id: int,
    target_ids: Sequence[int],
) -> Set[int]:
    ids = list(dict.fromkeys(int(tid) for tid in target_ids))
    if not ids:
        return set()
    p = _p(conn)
    disappeared: Set[int] = set()
    for chunk in _chunks(ids):
        placeholders = ",".join(p for _ in chunk)
        rows = conn.execute(
            "SELECT lp.target_id "
            "FROM ("
            "  SELECT e.target_id, MAX(s.id) AS last_present "
            "  FROM path_snapshots s "
            "  JOIN path_snapshot_entries e ON e.snapshot_id = s.id "
            f"  WHERE s.project_id = {p} "
            f"    AND e.target_id IN ({placeholders}) "
            "  GROUP BY e.target_id"
            ") lp "
            "WHERE EXISTS ("
            "  SELECT 1 FROM path_snapshots s2 "
            f"  WHERE s2.project_id = {p} "
            "    AND s2.id > lp.last_present "
            "    AND NOT EXISTS ("
            "      SELECT 1 FROM path_snapshot_entries e2 "
            "      WHERE e2.snapshot_id = s2.id "
            "        AND e2.target_id = lp.target_id"
            "    )"
            ")",
            (project_id, *chunk, project_id),
        ).fetchall()
        disappeared.update(int(row[0]) for row in rows)
    return disappeared


def _latest_can_be_materialized(
    latest: LatestTarget,
    *,
    kind: str,
    parent_target_id: Optional[int],
) -> bool:
    return (
        latest.materialization_state in PRE_OBSERVATION_STATES
        and latest.kind == kind
        and latest.parent_target_id == parent_target_id
    )


def _latest_can_be_reused(
    latest: LatestTarget,
    *,
    kind: str,
    parent_target_id: Optional[int],
    disappeared_target_ids: Set[int],
) -> bool:
    return (
        latest.kind == kind
        and latest.parent_target_id == parent_target_id
        and latest.id not in disappeared_target_ids
    )


def resolve_snapshot_target_ids(
    conn: Any,
    *,
    project_id: int,
    targets: Sequence[Tuple[str, str]],
    now_iso: str,
) -> SnapshotTargetResolution:
    """Resolve or mint target ids for a whole snapshot in bulk.

    This preserves the single-path resolver semantics while avoiding a
    database round trip per path against remote Postgres.

    Cold-start minting: on a fresh project/env with no ``path_targets``
    rows yet, both bulk reads return empty and every path falls through
    to ``_mint_target`` — one INSERT per path inside the same
    transaction. The first snapshot therefore still pays per-path write
    round trips; only steady-state re-resolution is read-optimized.
    That shape is intentional: minting is a one-time cost per target
    generation, and batching the INSERTs would complicate parent-id
    back-references (each child mint needs its parent's freshly minted
    id from earlier in the walk).
    """
    latest_by_path = _latest_targets_by_path(
        conn,
        project_id=project_id,
        path_strings=[path_string for path_string, _kind in targets],
    )
    disappeared = _targets_with_observed_disappearance(
        conn,
        project_id=project_id,
        target_ids=[latest.id for latest in latest_by_path.values()],
    )
    target_ids: Dict[str, int] = {}
    materialize_queue: List[int] = []
    for path_string, kind in targets:
        parent = _parent_path_string(path_string)
        parent_id = None if parent is None else target_ids[parent]
        latest = latest_by_path.get(path_string)
        if latest is not None and _latest_can_be_materialized(
            latest, kind=kind, parent_target_id=parent_id
        ):
            target_ids[path_string] = latest.id
            materialize_queue.append(latest.id)
            continue
        if latest is not None and _latest_can_be_reused(
            latest,
            kind=kind,
            parent_target_id=parent_id,
            disappeared_target_ids=disappeared,
        ):
            target_ids[path_string] = latest.id
            continue
        target_ids[path_string] = _mint_target(
            conn,
            project_id,
            path_string,
            kind,
            parent_id,
            1 if latest is None else latest.generation + 1,
            now_iso,
        )
    return SnapshotTargetResolution(
        target_ids=target_ids,
        materialize_target_ids=materialize_queue,
    )


__all__ = [
    "LatestTarget",
    "SnapshotTargetResolution",
    "resolve_snapshot_target_ids",
]
