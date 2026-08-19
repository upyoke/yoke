"""Board widgets — read daily commit/line rollup from the control plane.

Local ``.commit-cache.json`` feeds this table on rebuild; meters must not
treat the cache as a second authority for Overview-parity signals.
"""

from __future__ import annotations

from typing import Dict, List

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import project_id_filter, project_ref_where
from yoke_contracts.board.sql import days_ago_text_expr


def _scope_project_ids(db: BoardDBLike, scope: str) -> List[int]:
    if not scope or scope == "all":
        visibility, params = project_id_filter()
        rows = db.query_quiet(
            f"SELECT id FROM projects WHERE 1=1{visibility}",
            params,
        )
    else:
        where, params = project_ref_where(scope)
        rows = db.query_quiet(f"SELECT id FROM projects WHERE {where}", params)
    return [int(row[0]) for row in rows if row and row[0] is not None]


def code_lines_by_day(
    db: BoardDBLike, scope: str, days: int,
) -> Dict[str, int]:
    """Per-day lines_changed from ``project_code_days``."""

    return _series(db, scope, days, "lines_changed")


def code_commits_by_day(
    db: BoardDBLike, scope: str, days: int,
) -> Dict[str, int]:
    """Per-day commit_count from ``project_code_days``."""

    return _series(db, scope, days, "commit_count")


def _series(
    db: BoardDBLike, scope: str, days: int, column: str,
) -> Dict[str, int]:
    project_ids = _scope_project_ids(db, scope)
    if not project_ids:
        return {}
    markers = ", ".join("%s" for _ in project_ids)
    sql = (
        f"SELECT day, SUM({column}) AS total "
        "FROM project_code_days "
        f"WHERE project_id IN ({markers}) "
        f"AND day >= {days_ago_text_expr(days)} "
        "GROUP BY day"
    )
    counts: Dict[str, int] = {}
    for row in db.query_quiet(sql, tuple(project_ids)):
        if row and row[0] is not None:
            counts[str(row[0])] = int(row[1] or 0)
    return counts


def code_commit_days_all_time(
    db: BoardDBLike, scope: str,
) -> Dict[str, int]:
    """All-time commit_count by day (lifetime / streak union)."""

    project_ids = _scope_project_ids(db, scope)
    if not project_ids:
        return {}
    markers = ", ".join("%s" for _ in project_ids)
    sql = (
        "SELECT day, SUM(commit_count) AS total "
        "FROM project_code_days "
        f"WHERE project_id IN ({markers}) "
        "GROUP BY day"
    )
    params = tuple(project_ids)
    probe = getattr(db, "has_query_quiet", None)
    if callable(probe) and not probe(sql, params):
        return {}
    counts: Dict[str, int] = {}
    for row in db.query_quiet(sql, params):
        if row and row[0] is not None and int(row[1] or 0) > 0:
            counts[str(row[0])] = int(row[1] or 0)
    return counts


__all__ = [
    "code_commit_days_all_time",
    "code_commits_by_day",
    "code_lines_by_day",
]
