"""Dependency-first ordering for a planned candidate set."""

from __future__ import annotations

from typing import Dict, List, Tuple


def topological_sort(
    items: List[str],
    edges: List[Tuple[str, str]],
) -> Tuple[List[str], List[str]]:
    """Kahn's topological sort. ``edges`` are (blocker, dependent) pairs;
    blocker must come before dependent. Returns
    ``(ordered_items, cycle_items)`` — if ``cycle_items`` is non-empty the
    sort was incomplete.
    """
    item_set = set(items)
    # Only consider edges between items in the candidate set
    relevant_edges = [(b, d) for b, d in edges if b in item_set and d in item_set]

    # Build adjacency and in-degree
    adj: Dict[str, List[str]] = {i: [] for i in items}
    in_degree: Dict[str, int] = {i: 0 for i in items}
    for blocker, dependent in relevant_edges:
        adj[blocker].append(dependent)
        in_degree[dependent] = in_degree.get(dependent, 0) + 1

    # Initialize queue with zero in-degree items
    queue = sorted([i for i in items if in_degree[i] == 0])
    ordered: List[str] = []

    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for neighbor in sorted(adj.get(node, [])):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
        queue.sort()  # deterministic

    cycle_items = [i for i in items if i not in set(ordered)]
    return ordered, cycle_items


__all__ = ["topological_sort"]
