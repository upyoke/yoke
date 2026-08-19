"""Dependency-edge lookup for the joint gate's cross-item overlap check.

The overlap detector suppresses a conflict when the candidate and the other
item are already ordered by an ``item_dependencies`` edge. Both sides are
integer ``items.id`` values, matching the detector's currency.

Split from :mod:`db_mutation_gate_idea` so that at-cap file stays inside the
authored-file line limit.
"""

from __future__ import annotations

from typing import Any, Dict, List

from yoke_core.domain import db_backend
from yoke_core.domain.db_optional_queries import fetch_optional_rows


def load_dependency_pairs(
    conn: Any,
    item_id: int,
    others: List[Dict[str, Any]],
) -> set:
    """Return ``{(lo, hi)}`` internal-id pairs joined by an edge either way.

    Missing dependency tables on partial test DBs return an empty set.
    """
    other_ids = sorted({
        int(o["__item_id"]) for o in others if o.get("__item_id") is not None
    })
    if not other_ids:
        return set()
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    ph = ",".join([p] * len(other_ids))
    rows = fetch_optional_rows(
        conn,
        "SELECT dependent_item_id AS dependent_id, "
        "blocking_item_id AS blocking_id FROM item_dependencies "
        f"WHERE (dependent_item_id = {p} AND blocking_item_id IN ({ph})) "
        f"   OR (blocking_item_id = {p} AND dependent_item_id IN ({ph}))",
        (item_id, *other_ids, item_id, *other_ids),
        savepoint="idea_gate_dependency_pairs",
    )
    pairs: set = set()
    for row in rows:
        dep = row["dependent_id"] if hasattr(row, "keys") else row[0]
        blk = row["blocking_id"] if hasattr(row, "keys") else row[1]
        if dep is None or blk is None:
            continue
        a, b = int(dep), int(blk)
        pairs.add((min(a, b), max(a, b)))
    return pairs


__all__ = ["load_dependency_pairs"]
