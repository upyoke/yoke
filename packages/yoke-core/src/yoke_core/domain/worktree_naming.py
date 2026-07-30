"""Single source of truth for item worktree/branch names.

The name a user sees for a git worktree directory or a git branch is the
item's public reference (``{public_item_prefix}-{project_sequence}`` — for
example ``YOK-1913`` or ``BUZ-4``), never the raw internal ``items.id``.
Every worktree/branch *name-creation* site imports
:func:`worktree_name_for_item` so the public ref is the only name minted for
new worktrees and branches.

Recovering an item from a worktree/branch *name* is the inverse concern and
lives in
:func:`yoke_core.domain.item_worktree_resolution.resolve_item_id_by_worktree_name`;
that reverse-lookup reads ``item_worktrees`` so worktrees created under either
the new public-ref scheme or the legacy ``YOK-{internal_id}`` scheme keep
resolving to the correct internal id.
"""

from __future__ import annotations

from typing import Any, Optional, Set


def worktree_name_for_item(conn: Optional[Any], item_id: int) -> str:
    """Return the worktree/branch name for an item — its public ref.

    ``conn`` may be ``None`` (or point at a minimal schema that lacks
    ``items.project_sequence``); in those degraded cases — where the public
    sequence cannot be resolved — the name falls back to the legacy
    ``YOK-{item_id}`` form so callers without a usable connection still mint a
    stable, unique name.
    """
    item_id = int(item_id)
    if conn is not None:
        try:
            from yoke_core.domain.schema_common import (
                _column_exists,
                _table_exists,
            )

            # Only run the public-ref lookup when the schema can satisfy it.
            # Probing existence first avoids issuing a query that would fail on
            # a minimal schema — a failed query poisons the caller's open
            # transaction on Postgres (commands ignored until rollback).
            if _table_exists(conn, "projects") and _column_exists(
                conn, "items", "project_sequence"
            ):
                from yoke_core.domain.project_identity import render_item_ref

                name = render_item_ref(conn, item_id)
                if name:
                    return name
        except Exception:  # noqa: BLE001 - degrade to legacy name on any failure
            pass
    return f"YOK-{item_id}"


def candidate_worktree_names(conn: Any, item_id: int) -> Set[str]:
    """Return every name that could identify this item's worktree/branch.

    Covers the current public-ref name, the legacy ``YOK-{internal_id}``
    name, and every branch recorded in ``item_worktrees`` (active or
    released). Cleanup and health checks that must find a worktree created
    under either naming scheme use this instead of reconstructing a single
    ``YOK-{internal_id}`` guess.
    """
    item_id = int(item_id)
    names: Set[str] = {f"YOK-{item_id}", worktree_name_for_item(conn, item_id)}
    try:
        from yoke_core.domain.item_worktrees import list_item_worktrees

        for row in list_item_worktrees(conn, item_id):
            branch = str(row.get("branch") or "").strip()
            if branch:
                names.add(branch)
    except Exception:  # noqa: BLE001 - minimal schema / missing table
        pass
    return {name for name in names if name}


__all__ = [
    "candidate_worktree_names",
    "worktree_name_for_item",
]
