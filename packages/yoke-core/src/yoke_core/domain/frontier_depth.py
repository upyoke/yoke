"""Downstream-depth computation for frontier ranking."""

from __future__ import annotations

from typing import Any, Dict, List


_ACTIVATION_EDGES_SQL = """
SELECT d.blocking_item_id, d.dependent_item_id
FROM item_dependencies d
WHERE d.gate_point = 'activation'
"""


def _compute_downstream_depths(
    conn: Any,
) -> Dict[int, int]:
    """Compute max downstream depth for each item via activation-gate edges."""
    cursor = conn.cursor()
    cursor.execute(_ACTIVATION_EDGES_SQL)

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
