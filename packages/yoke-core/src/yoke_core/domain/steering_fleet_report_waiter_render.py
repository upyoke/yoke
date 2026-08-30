"""Render overdue background waiters without growing the main report module."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from yoke_core.domain.steering_fleet_report_waiters import (
    OverdueBackgroundWaiter,
)


def wake_recipe(entry: OverdueBackgroundWaiter) -> str:
    """The item-addressed send form a steering seat can paste verbatim."""
    message = (
        "Your registered background waiter is overdue with no completion "
        "record; inspect the fleet report and continue or re-arm."
    )
    return f'printf %s "{message}" | yoke say --item {entry.public_ref} --stdin'


def waiter_dict(entry: OverdueBackgroundWaiter) -> dict[str, Any]:
    return {
        "session_id": entry.session_id,
        "item_id": entry.item_id,
        "public_ref": entry.public_ref,
        "waiter_id": entry.waiter_id,
        "kind": entry.kind,
        "watched_fact": entry.watched_fact,
        "armed_at": entry.armed_at,
        "expected_by": entry.expected_by,
        "armed_seconds": entry.armed_seconds,
        "overdue_seconds": entry.overdue_seconds,
        "recovery": wake_recipe(entry),
    }


def waiter_lines(
    waiters: Sequence[OverdueBackgroundWaiter],
    *,
    limit: int,
    duration: Callable[[int], str],
) -> list[str]:
    lines = [
        f"  {entry.public_ref}  session {entry.session_id}  "
        f"{entry.watched_fact}  overdue {duration(entry.overdue_seconds)}; "
        f"no completion; wake: {wake_recipe(entry)}"
        for entry in waiters[:limit]
    ]
    if len(waiters) > limit:
        lines.append(f"  ... {len(waiters) - limit} more")
    return lines


__all__ = ["waiter_dict", "waiter_lines", "wake_recipe"]
