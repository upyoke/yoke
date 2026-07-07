"""Item-lifecycle integration hooks for path claims.

Owns the side effect that fires when an item transitions to a terminal
state that should not leave non-terminal path claims behind. Called by
the canonical status-write path in
:mod:`yoke_core.domain.backlog_update_op` after the item's new
status has been committed.

Behaviour:

* When the new status is ``cancelled`` or ``stopped``, every non-
  terminal claim attached to the item is cancelled with
  ``cancel_reason='item-cancelled'`` (or ``'item-stopped'``).
  Cancellation emits the ``PathClaimCancelled`` event for each claim
  through :mod:`yoke_core.domain.path_claims_events`.
* The hook is fail-open against minimal-fixture environments that
  lack the ``path_claims`` table — it returns ``None`` silently.
* Cancellations are best-effort: a single claim's failure is logged
  through the events module's WARN emission (``PathClaimCancelled``
  with a non-``completed`` outcome would mislabel the actual outcome,
  so failures surface through the existing event side effect of
  ``cancel`` itself).
"""

from __future__ import annotations

from typing import Any, List, Optional

from yoke_core.domain import db_backend


_TERMINAL_STATES = ("cancelled", "stopped")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _non_terminal_claim_ids_for_item(
    conn: Any, item_id: int
) -> List[int]:
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT id FROM path_claims "
            f"WHERE item_id = {p} AND state IN "
            "('planned', 'blocked', 'active')",
            (item_id,),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []
    return [int(r[0]) for r in rows]


def cancel_claims_on_item_terminal(
    conn: Any,
    *,
    item_id: int,
    new_status: str,
) -> Optional[int]:
    """Cancel every non-terminal path claim attached to ``item_id``.

    Returns the count of claims that transitioned to ``cancelled``
    (zero is a valid result), or ``None`` when the new status is not
    one of the item-terminal triggers.
    """
    if new_status not in _TERMINAL_STATES:
        return None

    claim_ids = _non_terminal_claim_ids_for_item(conn, item_id)
    if not claim_ids:
        return 0

    try:
        from yoke_core.domain import path_claims_events as _events
    except ImportError:  # pragma: no cover - defensive
        _events = None  # type: ignore[assignment]
    try:
        from yoke_core.domain.path_claims import (
            IllegalTransition,
            cancel as _cancel_claim,
            get_claim,
        )
    except ImportError:  # pragma: no cover - defensive
        return 0

    reason = f"item-{new_status}"
    cancelled = 0
    for claim_id in claim_ids:
        try:
            _cancel_claim(conn, claim_id=claim_id, reason=reason)
        except IllegalTransition:
            # Claim moved to a different terminal state between read
            # and cancel; skip without unwinding the rest.
            continue
        cancelled += 1
        if _events is not None:
            try:
                _events.emit_cancelled(
                    conn=conn,
                    claim=get_claim(conn, claim_id),
                    reason=reason,
                )
            except Exception:
                # Event emission is best-effort; never fail the
                # status mutation because the audit emit slipped.
                pass
    return cancelled


__all__ = [
    "cancel_claims_on_item_terminal",
]
