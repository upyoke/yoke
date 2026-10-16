"""Public item references name new lanes; recorded branches identify existing lanes."""

from __future__ import annotations

from typing import Any, Optional, Set


class ItemWorktreeIdentityUnresolved(LookupError):
    """No authoritative public reference for an item that needs a lane name.

    Raised by :func:`worktree_name_for_item` instead of returning a name
    built from ``items.id``. ``items.id`` and ``project_sequence`` are
    independent counters, so such a name reads as — and in another project's
    numbering *is* — a different item's reference.
    """


def worktree_name_for_item(conn: Optional[Any], item_id: int) -> str:
    """Return the worktree/branch name for an item — its public ref.

    Raises :class:`ItemWorktreeIdentityUnresolved` when the item's own
    prefix and sequence cannot be read, including when ``conn`` is ``None``
    or points at a schema without the project identity tables. The caller
    reports that refusal; it does not mint a name from the storage key,
    because the number in such a name belongs to whichever item owns it as
    a sequence and the repository would then carry that claim.
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
                from yoke_core.domain.item_ref_render import render_item_refs

                # A name, not message text: the batch reader answers with
                # nothing for an id no identity row backs, which is the
                # case this refuses for.
                name = render_item_refs(conn, [item_id]).get(item_id)
                if name:
                    return name
        except ItemWorktreeIdentityUnresolved:
            raise
        except Exception as exc:  # noqa: BLE001 - any read shortfall refuses
            raise ItemWorktreeIdentityUnresolved(
                "cannot name a worktree lane: reading the item's project "
                "prefix and sequence failed"
            ) from exc
    raise ItemWorktreeIdentityUnresolved(
        "cannot name a worktree lane: the item's project prefix and "
        "sequence do not resolve, and a name minted from the storage key "
        "would name a different item"
    )


def candidate_worktree_names(conn: Any, item_id: int) -> Set[str]:
    """Return the public reference and branches recorded for this item."""
    item_id = int(item_id)
    names: Set[str] = set()
    try:
        names.add(worktree_name_for_item(conn, item_id))
    except ItemWorktreeIdentityUnresolved:
        pass
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
    "ItemWorktreeIdentityUnresolved",
    "candidate_worktree_names",
    "worktree_name_for_item",
]
