"""Advance preflight refusal when ``items.blocked = 1``.

The flag is operator-set (or set by the idea path-claim fallback) and
signals that an upstream coordination is unresolved. While the flag is
set the item must not advance into ``implementing`` (or any later
status) — the operator must call ``/yoke unblock YOK-N`` first, which
restores the preserved lifecycle status without changing it.

The pre-commit worktree status guard
(:mod:`yoke_core.domain.check_worktree_status_invariant`) is
intentionally NOT changed: blocked is a routing/dispatch hold, not a
filesystem hold. An item that is already in a worktree can keep
committing while blocked; only the next status forward-transition is
refused by this gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.queries import is_blocked


@dataclass
class AdvanceBlockedDecision:
    """Result of the advance blocked-flag gate."""

    blocked: bool
    reason: Optional[str] = None
    rendered_blocker: Optional[str] = None


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def evaluate(conn: Any, item_id: int) -> AdvanceBlockedDecision:
    """Return whether the advance must be refused for ``items.blocked = 1``.

    The gate is read-only: it inspects the items row and returns a
    decision struct. Callers (the advance preflight orchestrator)
    surface ``rendered_blocker`` verbatim and stop the advance when
    ``blocked`` is True.
    """
    p = _p(conn)
    row = conn.execute(
        f"SELECT blocked, blocked_reason FROM items WHERE id = {p}",
        (item_id,),
    ).fetchone()
    if row is None:
        return AdvanceBlockedDecision(blocked=False)
    flag, reason = row[0], row[1]
    if not is_blocked(flag):
        return AdvanceBlockedDecision(blocked=False)
    rendered = (
        f"**Blocked:** YOK-{item_id} has items.blocked=1 — "
        f"the operator-set blocked flag refuses forward progression. "
        f"Run /yoke unblock YOK-{item_id} once the underlying "
        f"coordination is resolved."
    )
    if reason:
        rendered += f"\n\nReason: {reason}"
    return AdvanceBlockedDecision(
        blocked=True,
        reason=str(reason) if reason else None,
        rendered_blocker=rendered,
    )


__all__ = ["AdvanceBlockedDecision", "evaluate"]
