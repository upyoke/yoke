"""Event emission for the advance path-claim activation phase.

Sibling helper to :mod:`yoke_core.domain.advance_path_claim_activation`.
Owns the ``PathClaimActivationBlocked`` event emission for the phase's
early-return blocked branch, including blocked-reason parsing and
phase-local idempotency. The parent module's source file is near the
per-file line cap; this sibling absorbs the work so the parent stays
inside the cap.

The canonical event emitter
:func:`yoke_core.domain.path_claims_events.emit_activation_blocked`
already exists; this module wires the activation phase's blocked branch
to it and parses the upstream claim id from the ``blocked_reason``
string.
"""

from __future__ import annotations

from typing import Any, Optional, Set, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims_dependency_propagation import (
    _blocked_reason_claim_id,
)
from yoke_core.domain.path_claims_events import emit_activation_blocked


EmittedKey = Tuple[str, int, int]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _claim_integration_target(
    conn: Any, claim_id: int,
) -> Optional[str]:
    p = _p(conn)
    row = conn.execute(
        f"SELECT integration_target FROM path_claims WHERE id = {p}",
        (claim_id,),
    ).fetchone()
    if row is None:
        return None
    return None if row[0] is None else str(row[0])


def _item_project(
    conn: Any, item_id: int,
) -> Optional[str]:
    p = _p(conn)
    row = conn.execute(
        "SELECT p.slug FROM items i "
        "LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {p}",
        (item_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def record_blocked_claim(
    conn: Any,
    *,
    result,
    outcome_cls,
    claim_id: int,
    blocked_reason,
    item_id: int,
    session_id: Optional[str],
    emitted_keys: Set[EmittedKey],
) -> None:
    """Record a blocked-claim outcome on ``result`` and emit the event.

    Mutates ``result`` in place (appends the error message and the
    ``ActivationOutcome``) and emits one ``PathClaimActivationBlocked``
    event per ``(session_id, claim_id, item_id)`` key within the phase
    invocation. ``outcome_cls`` is the ``ActivationOutcome`` dataclass
    passed in by the caller to avoid a circular import.
    """
    upstream = blocked_reason or "(unknown upstream)"
    result.blocked_errors.append(
        f"claim {claim_id} is blocked: {upstream}; "
        f"resolve the upstream claim before activating"
    )
    result.outcomes.append(
        outcome_cls(
            claim_id=claim_id,
            state_before="blocked",
            state_after="blocked",
            error=f"blocked: {upstream}",
        )
    )
    key: EmittedKey = (session_id or "", claim_id, item_id)
    if key in emitted_keys:
        return
    emitted_keys.add(key)
    emit_activation_blocked(
        conn=conn,
        claim_id=claim_id,
        integration_target=_claim_integration_target(conn, claim_id),
        reason=upstream,
        blocking_claim_id=_blocked_reason_claim_id(upstream),
        item_id=item_id,
        project=_item_project(conn, item_id),
        session_id=session_id,
    )


__all__ = ["record_blocked_claim", "EmittedKey"]
