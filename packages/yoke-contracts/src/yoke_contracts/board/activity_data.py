"""Read activity-day counts for an authorized board scope."""

from typing import Any, Dict
from yoke_contracts.board.project_scope import project_filter


def activity_day_counts(db: Any, scope: str) -> Dict[str, int]:
    pf, params = project_filter(scope, "a")
    sql = (
        "SELECT a.day AS day,"
        "       COUNT(DISTINCT a.item_id) AS cnt "
        "FROM item_activity_days a "
        "WHERE 1=1 "
        f"  {pf}"
        " GROUP BY a.day ORDER BY a.day"
    )
    rows = db.query_quiet(sql, params)
    counts: Dict[str, int] = {}
    for row in rows:
        if row[0]:
            counts[row[0]] = int(row[1])
    return counts
