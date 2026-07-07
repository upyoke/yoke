"""Downstream-depth computation for frontier ranking."""

from __future__ import annotations

from typing import Any, Dict, List


_ACTIVATION_EDGES_SQL = """
SELECT d.blocking_item, d.dependent_item
FROM item_dependencies d
WHERE d.gate_point = 'activation'
"""


def _compute_downstream_depths(
    conn: Any,
) -> Dict[str, int]:
    """Compute max downstream depth for each item via activation-gate edges."""
    cursor = conn.cursor()
    cursor.execute(_ACTIVATION_EDGES_SQL)

    adj: Dict[str, List[str]] = {}
    for blocker, dependent in cursor.fetchall():
        adj.setdefault(blocker, []).append(dependent)

    memo: Dict[str, int] = {}
    on_stack: set[str] = set()

    def max_depth(node: str) -> int:
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
