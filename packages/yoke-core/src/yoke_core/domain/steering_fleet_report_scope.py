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

from yoke_core.domain.steering_scope_membership import (
    scope_document,
    scope_member_item_ids,
)

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


def seat_landed_open(
    rows: Sequence[T],
    members: Optional[set[int]],
    scope: Mapping[str, Any],
) -> tuple[T, ...]:
    """Landings this seat can name.

    A project-wide seat's staffing roster is unlinked plus CURRENT-PLAN, but
    a landing is a delivery-plane fact: the next release enrolls the same
    rows, and a document link must not hide a close-out. A document seat
    still sees only its members.
    """
    if scope_document(scope) is None:
        return tuple(rows)
    return members_only(rows, members)


def seat_claim_holders(
    holders: Sequence[T],
    members: Optional[set[int]],
    landed_open: Sequence[Any],
) -> tuple[T, ...]:
    """Staffing membership, plus holders of landings this seat can already see."""
    scoped = members_only(holders, members)
    visible = {int(entry.item_id) for entry in landed_open}
    seen = {(holder.session_id, holder.item_id) for holder in scoped}
    extra = tuple(
        holder
        for holder in holders
        if int(holder.item_id) in visible
        and (holder.session_id, holder.item_id) not in seen
    )
    return scoped + extra


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


__all__ = [
    "members_only",
    "seat_claim_holders",
    "seat_landed_open",
    "seat_members",
    "sessions_only",
]
