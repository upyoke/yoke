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
        "(dependent_item_id, blocking_item_id, gate_point, satisfaction, "
        "source, rationale, evidence_json, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, 'test', 'seeded by test', '{{}}', '2026-01-01T00:00:00Z')",
        (
            int(str(dependent).rsplit("-", 1)[-1]),
            int(str(blocking).rsplit("-", 1)[-1]),
            gate_point,
            satisfaction,
        ),
    )
    conn.commit()
    conn.close()


def _stored_item_id(value):
    if value is None:
        return None
    return value if isinstance(value, int) else int(str(value).rsplit("-", 1)[-1])


def _dependency_rows(path, *, dependent=None, blocking=None):
    """Return stored id rows matching the given direction filter."""
    conn = _conn(path)
    p = _p(conn)
    dependent = _stored_item_id(dependent)
    blocking = _stored_item_id(blocking)
    select = "SELECT dependent_item_id, blocking_item_id, gate_point, satisfaction FROM item_dependencies "
    if dependent is not None and blocking is not None:
        rows = conn.execute(
            select
            + f"WHERE dependent_item_id = {p} AND blocking_item_id = {p} ORDER BY gate_point",
            (dependent, blocking),
        ).fetchall()
    elif dependent is not None:
        rows = conn.execute(
            select + f"WHERE dependent_item_id = {p} ORDER BY blocking_item_id, gate_point",
            (dependent,),
        ).fetchall()
    elif blocking is not None:
        rows = conn.execute(
            select + f"WHERE blocking_item_id = {p} ORDER BY dependent_item_id, gate_point",
            (blocking,),
        ).fetchall()
    else:
        rows = conn.execute(select + "ORDER BY id").fetchall()
    conn.close()
    return [(int(r[0]), int(r[1]), r[2], r[3]) for r in rows]
