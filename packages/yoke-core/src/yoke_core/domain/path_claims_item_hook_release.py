"""Item-lifecycle release hook for path claims.

Sibling of :mod:`path_claims_item_hook` that owns the *release*
counterpart to its sibling's *cancel* behaviour. Called from the
canonical status-write path in
:mod:`yoke_core.domain.backlog_update_op` after the item's new
status has been committed.

Why a sibling instead of expanding ``path_claims_item_hook.py``?
The cancel hook is small but the release path adds structural
parallelism that the spec wants surfaced as its own
module: terminal-release semantics differ from cancellation
semantics, the reason strings are distinct (``item-release`` /
``item-done`` versus ``item-cancelled`` / ``item-stopped``), and
the emitted event is :func:`emit_released` rather than
:func:`emit_cancelled`. Keeping the two hooks in their own files
also keeps each at a comfortable distance from the 350-line cap.

Behaviour:

* When the new status is ``release`` or ``done``, every non-
  terminal claim attached to the item is *released* (not
  cancelled) with ``release_reason='item-release'`` /
  ``release_reason='item-done'``. Each release emits the
  ``PathClaimReleased`` event through
  :mod:`yoke_core.domain.path_claims_events`.
* Each successful release re-runs downstream unblock propagation so
  serial claims blocked on the released claim can move back to
  ``planned`` when no live overlap remains.
* The hook is fail-open against minimal-fixture environments that
  lack the ``path_claims`` table — it returns ``None`` silently
  without raising.
* ``release`` is the primary trigger: it marks merge-complete and
  is the moment item-linked work has actually landed in the
  ``integration_target``. ``done`` is a backstop so a fast-path
  done transition (or any flow that bypasses ``release``) cannot
  leave a non-terminal claim behind.
* Releases are best-effort per claim; one claim's failure does
  not unwind the rest of the iteration.
"""

from __future__ import annotations

from typing import Any, List, Optional

from yoke_core.domain import db_backend


_TERMINAL_STATES = ("release", "done")


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


def release_claims_on_item_terminal(
    conn: Any,
    *,
    item_id: int,
    new_status: str,
) -> Optional[int]:
    """Release every non-terminal path claim attached to ``item_id``.

    Returns the count of claims that transitioned to ``released``
    (zero is a valid result), or ``None`` when ``new_status`` is
    not one of the terminal-release triggers (``release`` /
    ``done``).
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
            get_claim,
            release as _release_claim,
        )
    except ImportError:  # pragma: no cover - defensive
        return 0

    try:
        from yoke_core.domain.path_claims_dependency_propagation import (
            propagate_release_unblock,
        )
    except ImportError:  # pragma: no cover - defensive
        propagate_release_unblock = None  # type: ignore[assignment]

    reason = f"item-{new_status}"
    released = 0
    for claim_id in claim_ids:
        try:
            _release_claim(conn, claim_id=claim_id, reason=reason)
        except IllegalTransition:
            continue
        released += 1
        if _events is not None:
            try:
                _events.emit_released(
                    conn=conn,
                    claim=get_claim(conn, claim_id),
                    reason=reason,
                )
            except Exception:
                pass
        if propagate_release_unblock is not None:
            try:
                propagate_release_unblock(
                    conn, released_claim_id=claim_id,
                )
            except Exception:
                pass
    return released


__all__ = [
    "release_claims_on_item_terminal",
]
