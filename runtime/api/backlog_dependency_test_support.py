"""Seed and query helpers for dependency reconciliation tests."""

from runtime.api.fixtures.backlog_inserts import insert_item_worktree
from runtime.api.test_backlog import _conn, _p


def _seed_active_item_lane(path, *, item_id: int, branch: str) -> None:
    conn = _conn(path)
    try:
        insert_item_worktree(
            conn,
            item_id=item_id,
            branch=branch,
            lane_role="implementation",
        )
    finally:
        conn.close()


def _seed_dependency(
    path, dependent, blocking, gate_point="activation", satisfaction="status:done"
):
    """Insert an item_dependencies row for close-path reconciliation tests."""
    conn = _conn(path)
    p = _p(conn)
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, "
        "source, rationale, evidence_json, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, 'test', 'seeded by test', '{{}}', '2026-01-01T00:00:00Z')",
        (dependent, blocking, gate_point, satisfaction),
    )
    conn.commit()
    conn.close()


def _dependency_rows(path, *, dependent=None, blocking=None):
    """Return rows matching the given direction filter."""
    conn = _conn(path)
    p = _p(conn)
    select = "SELECT dependent_item, blocking_item, gate_point, satisfaction FROM item_dependencies "
    if dependent is not None and blocking is not None:
        rows = conn.execute(
            select
            + f"WHERE dependent_item = {p} AND blocking_item = {p} ORDER BY gate_point",
            (dependent, blocking),
        ).fetchall()
    elif dependent is not None:
        rows = conn.execute(
            select + f"WHERE dependent_item = {p} ORDER BY blocking_item, gate_point",
            (dependent,),
        ).fetchall()
    elif blocking is not None:
        rows = conn.execute(
            select + f"WHERE blocking_item = {p} ORDER BY dependent_item, gate_point",
            (blocking,),
        ).fetchall()
    else:
        rows = conn.execute(select + "ORDER BY id").fetchall()
    conn.close()
    return [tuple(r) for r in rows]
