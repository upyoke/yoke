"""Contract legacy worktree fields into universal item-lane references."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.item_worktree_schema import (
    ensure_epic_item_worktree_references,
    ensure_item_worktree_schema,
)
from yoke_core.domain.item_worktrees import (
    validate_item_worktree_roles,
)
from yoke_core.domain.migrations.workflow_item_worktree_backfill import (
    backfill_item_lanes as _backfill_item_lanes,
    backfill_worker_lanes as _backfill_worker_lanes,
    ensure_required_peers as _ensure_required_peers,
)
from yoke_core.domain.migrations.workflow_item_worktree_sources import (
    ItemLaneSource as _ItemLaneSource,
    WorkerLaneSource as _WorkerLaneSource,
    assert_source_roles_do_not_conflict as _assert_source_roles_do_not_conflict,
    clean as _clean,
    item_lane_sources as _item_lane_sources,
    resolve_worker_lane_path as _resolve_worker_lane_path,
    worker_lane_sources as _worker_lane_sources,
    worker_source_groups as _worker_source_groups,
)
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _table_exists,
)
from yoke_core.domain.workflow_behavior import LANE_WORKER

MIGRATION_NAME = "workflow_item_worktree_records"


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _legacy_row_counts(conn: Any) -> dict[str, int]:
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("items", "epic_tasks", "epic_dispatch_chains")
        if _table_exists(conn, table)
    }


def _assert_legacy_row_counts(conn: Any, expected: dict[str, int]) -> None:
    actual = {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in expected
    }
    if actual != expected:
        raise AssertionError(
            f"legacy worktree source row counts changed: {expected} -> {actual}"
        )


def _assert_item_lanes(
    conn: Any,
    sources: list[_ItemLaneSource],
) -> None:
    marker = _placeholder(conn)
    for source in sources:
        expected_state = "released" if source.released else "active"
        row = conn.execute(
            "SELECT id FROM item_worktrees WHERE item_id="
            + marker
            + " AND branch="
            + marker
            + " AND lane_role="
            + marker
            + " AND state="
            + marker
            + " ORDER BY id DESC LIMIT 1",
            (
                source.item_id,
                source.branch,
                source.lane_role,
                expected_state,
            ),
        ).fetchone()
        if row is None:
            raise AssertionError(
                f"items id={source.item_id} branch {source.branch!r} lacks its "
                f"{expected_state} {source.lane_role} lane"
            )


def _assert_worker_links(
    conn: Any,
    sources: list[_WorkerLaneSource],
) -> None:
    marker = _placeholder(conn)
    for (item_id, branch), group in _worker_source_groups(sources).items():
        path_resolution = _resolve_worker_lane_path(item_id, branch, group)
        expected_state = (
            "released" if all(source.released for source in group) else "active"
        )
        linked_ids: set[int] = set()
        for source in group:
            link = conn.execute(
                f"SELECT item_worktree_id FROM {source.table} WHERE id={marker}",
                (source.row_id,),
            ).fetchone()
            if link is None or link[0] is None:
                raise AssertionError(
                    f"{source.table} id={source.row_id} lacks an item worktree link"
                )
            lane_id = int(link[0])
            linked_ids.add(lane_id)
            lane = conn.execute(
                "SELECT item_id, branch, path, lane_role, state "
                "FROM item_worktrees WHERE id=" + marker,
                (lane_id,),
            ).fetchone()
            if lane is None:
                raise AssertionError(
                    f"{source.table} id={source.row_id} references missing "
                    f"item_worktrees id={lane_id}"
                )
            actual = (
                int(lane[0]),
                str(lane[1]),
                _clean(lane[2]),
                str(lane[3]),
                str(lane[4]),
            )
            if actual[0] != item_id or actual[1] != branch:
                raise AssertionError(
                    f"{source.table} id={source.row_id} links to "
                    f"{actual[0]}:{actual[1]!r}, expected {item_id}:{branch!r}"
                )
            if path_resolution.clear_released_path and actual[2] is not None:
                raise AssertionError(
                    f"{source.table} id={source.row_id} links to path "
                    f"{actual[2]!r}, expected released history without an owning path"
                )
            if path_resolution.path is not None and actual[2] != path_resolution.path:
                raise AssertionError(
                    f"{source.table} id={source.row_id} links to path "
                    f"{actual[2]!r}, expected {path_resolution.path!r}"
                )
            if actual[3:] != (LANE_WORKER, expected_state):
                raise AssertionError(
                    f"{source.table} id={source.row_id} links to "
                    f"{actual[3]!r}/{actual[4]!r}, expected "
                    f"{LANE_WORKER!r}/{expected_state!r}"
                )
        if len(linked_ids) != 1:
            raise AssertionError(
                f"legacy sources for item {item_id} branch {branch!r} "
                f"reference different lane records: {sorted(linked_ids)}"
            )


def _assert_links(conn: Any) -> None:
    item_sources = _item_lane_sources(conn)
    worker_sources = _worker_lane_sources(conn)
    _assert_source_roles_do_not_conflict(item_sources, worker_sources)
    _assert_item_lanes(conn, item_sources)
    _assert_worker_links(conn, worker_sources)


def apply(conn: Any) -> None:
    """Create universal lane records and link every usable epic lane once."""
    before = _legacy_row_counts(conn)
    item_sources = _item_lane_sources(conn)
    worker_sources = _worker_lane_sources(conn)
    _assert_source_roles_do_not_conflict(item_sources, worker_sources)
    ensure_item_worktree_schema(conn)
    if _table_exists(conn, "epic_tasks"):
        _add_column_if_not_exists(
            conn, "epic_tasks", "item_worktree_id", "INTEGER DEFAULT NULL"
        )
    if _table_exists(conn, "epic_dispatch_chains"):
        _add_column_if_not_exists(
            conn,
            "epic_dispatch_chains",
            "item_worktree_id",
            "INTEGER DEFAULT NULL",
        )
    ensure_epic_item_worktree_references(conn)
    _backfill_item_lanes(conn, item_sources)
    _backfill_worker_lanes(conn, worker_sources)
    _ensure_required_peers(conn)
    _assert_links(conn)
    _assert_legacy_row_counts(conn, before)
    for (item_id,) in conn.execute(
        "SELECT DISTINCT item_id FROM item_worktrees WHERE state='active' ORDER BY item_id"
    ).fetchall():
        validate_item_worktree_roles(conn, int(item_id))
    conn.commit()


def invariants(conn: Any) -> None:
    """Verify item-lane links and active lane policy after contraction."""
    if not _table_exists(conn, "item_worktrees"):
        raise AssertionError("item_worktrees table is missing")
    _assert_links(conn)
    for (item_id,) in conn.execute(
        "SELECT DISTINCT item_id FROM item_worktrees WHERE state='active' ORDER BY item_id"
    ).fetchall():
        validate_item_worktree_roles(conn, int(item_id))


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
