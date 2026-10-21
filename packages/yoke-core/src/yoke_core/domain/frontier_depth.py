"""Downstream-depth computation for frontier ranking."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence


#: Activation edges reachable downstream from a blocker in the requested
#: projects. A chain may pass through another project's item, so the walk
#: follows every edge it reaches rather than only in-scope ones. ``{scope}``
#: is the frontier's ``AND i.project_id IN (...)`` clause.
_ACTIVATION_EDGES_SQL = """
WITH RECURSIVE reached(item_id) AS (
    SELECT d.blocking_item_id
    FROM item_dependencies d
    JOIN items i ON i.id = d.blocking_item_id
    WHERE d.gate_point = 'activation'{scope}
    UNION
    SELECT d.dependent_item_id
    FROM item_dependencies d
    JOIN reached r ON r.item_id = d.blocking_item_id
    WHERE d.gate_point = 'activation'
)
SELECT d.blocking_item_id, d.dependent_item_id
FROM item_dependencies d
JOIN reached r ON r.item_id = d.blocking_item_id
WHERE d.gate_point = 'activation'
"""


def _compute_downstream_depths(
    conn: Any, scope_clause: str, scope_params: Sequence[Any]
) -> Dict[int, int]:
    """Compute max downstream depth for each in-scope blocker's activation chain."""
    cursor = conn.cursor()
    cursor.execute(_ACTIVATION_EDGES_SQL.format(scope=scope_clause), tuple(scope_params))

    adj: Dict[int, List[int]] = {}
    for blocker, dependent in cursor.fetchall():
        adj.setdefault(int(blocker), []).append(int(dependent))

    memo: Dict[int, int] = {}
    on_stack: set[int] = set()

    def max_depth(node: int) -> int:
        if node in memo:
            return memo[node]
        if node in on_stack:
            return 0
        on_stack.add(node)
        children = adj.get(node, [])
        memo[node] = 0 if not children else 1 + max(max_depth(child) for child in children)
        on_stack.discard(node)
        return memo[node]

    for node in list(adj.keys()):
        max_depth(node)

    return memo
