"""Narrow one fleet report's rows to the seat that asked for it.

A seat narrowed to a strategy document steers that document's items, so its
report shows those and nothing else. This module is where that narrowing
happens, once, for every item-keyed section: the report composer stays a
list of what to look at, not a list of what to hide.

Delivery-plane and machine facts are deliberately not narrowed. A launch
that never bound a session has no item to attribute it to, and machines are
shared by every seat running on them, so both stay project-wide facts that
the combined report already renders once for all held scopes.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence, TypeVar

from yoke_core.domain.steering_scope_membership import scope_member_item_ids

T = TypeVar("T")


def seat_members(
    conn: Any,
    scope: Mapping[str, Any],
) -> Optional[set[int]]:
    """The item ids one seat covers, or ``None`` for a whole-project seat."""
    return scope_member_item_ids(conn, scope)


def members_only(rows: Sequence[T], members: Optional[set[int]]) -> tuple[T, ...]:
    """Keep the rows a narrowed seat covers; keep everything for a project seat.

    ``None`` filters nothing -- it is the project-wide seat, not an empty
    membership. Every row this filters names its item in ``item_id``.
    """
    if members is None:
        return tuple(rows)
    return tuple(row for row in rows if int(row.item_id) in members)


def sessions_only(
    rows: Sequence[T],
    *,
    session_ids: Iterable[str],
    members: Optional[set[int]],
) -> tuple[T, ...]:
    """Keep session-keyed rows whose session holds one of this seat's items."""
    if members is None:
        return tuple(rows)
    covered = set(session_ids)
    return tuple(row for row in rows if row.session_id in covered)


__all__ = ["members_only", "seat_members", "sessions_only"]
