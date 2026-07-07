"""Bulk lineage expansion for path-claim overlap checks."""

from __future__ import annotations

from typing import Any, Optional, Sequence


def expand_lineage(
    conn: Any, target_ids: Sequence[int],
) -> list[int]:
    """Return candidate target ids unioned with ancestors and descendants.

    Reads the path-target parent graph once, then walks it in memory. This
    keeps large claims from rendering or classifying overlap with one
    recursive DB query per claimed file.
    """
    if not target_ids:
        return []
    rows = conn.execute(
        "SELECT id, parent_target_id FROM path_targets"
    ).fetchall()
    parents: dict[int, Optional[int]] = {}
    children: dict[int, list[int]] = {}
    for row in rows:
        target_id = int(row[0])
        parent_id = None if row[1] is None else int(row[1])
        parents[target_id] = parent_id
        if parent_id is not None:
            children.setdefault(parent_id, []).append(target_id)

    seen: set[int] = set()
    for raw in target_ids:
        tid = int(raw)
        seen.add(tid)
        ancestor_seen: set[int] = set()
        parent_id = parents.get(tid)
        while parent_id is not None and parent_id not in ancestor_seen:
            seen.add(parent_id)
            ancestor_seen.add(parent_id)
            parent_id = parents.get(parent_id)

        stack = list(children.get(tid, ()))
        while stack:
            child_id = stack.pop()
            if child_id in seen:
                continue
            seen.add(child_id)
            stack.extend(children.get(child_id, ()))
    return sorted(seen)


__all__ = ["expand_lineage"]
