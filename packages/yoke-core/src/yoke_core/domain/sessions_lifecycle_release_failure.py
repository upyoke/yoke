"""Failure-mode disambiguation + event emission for claim release.

Split out of ``sessions_lifecycle_release.py`` to keep the parent module
under the 350-line hard limit. Owns:

- The ``RELEASE_FAILURE_*`` failure-tag constants.
- ``diagnose_target_release_miss`` — typed-target variant: distinguishes
  ``not_owned`` / ``already_terminal`` / ``item_not_found`` for any
  WorkClaimTarget kind.
- ``diagnose_release_miss`` — legacy text-id variant kept as a thin
  wrapper for callers still passing item-id strings.
- ``emit_target_release_failed`` / ``emit_release_failed`` — emit the
  canonical ``ItemClaimReleaseFailed`` event with the standard payload,
  enriched with target_kind / process_key when applicable.
- ``read_item_status`` — best-effort lookup of the item's current
  status, included in the event payload as ``target_status``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import db_backend
from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_ITEM_CLAIM_RELEASE_FAILED
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    WorkClaimTarget,
)

RELEASE_FAILURE_NOT_OWNED = "not_owned"
RELEASE_FAILURE_ALREADY_TERMINAL = "already_terminal"
RELEASE_FAILURE_ITEM_NOT_FOUND = "item_not_found"
RELEASE_FAILURE_DOMAIN_ERROR = "domain_error"

ALL_RELEASE_FAILURE_REASONS = frozenset({
    RELEASE_FAILURE_NOT_OWNED,
    RELEASE_FAILURE_ALREADY_TERMINAL,
    RELEASE_FAILURE_ITEM_NOT_FOUND,
    RELEASE_FAILURE_DOMAIN_ERROR,
})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _target_clauses(conn: Any, target: WorkClaimTarget) -> tuple[str, list[Any]]:
    p = _p(conn)
    if target.kind == TARGET_KIND_ITEM:
        return (f"target_kind='item' AND item_id = {p}", [target.item_id])
    if target.kind == TARGET_KIND_EPIC_TASK:
        return (
            f"target_kind='epic_task' AND epic_id = {p} AND task_num = {p}",
            [target.epic_id, target.task_num],
        )
    return (
        f"target_kind='process' AND process_key = {p}",
        [target.process_key],
    )


def diagnose_target_release_miss(
    conn: Any,
    target: WorkClaimTarget,
) -> tuple[str, Optional[str]]:
    """Disambiguate the "no active claim for this session" branch (typed).

    Returns ``(failure_reason, holder_session_id)``.
    """
    where, params = _target_clauses(conn, target)

    other_active = conn.execute(
        f"SELECT session_id FROM work_claims WHERE {where} "
        f"AND released_at IS NULL ORDER BY claimed_at DESC, id DESC LIMIT 1",
        params,
    ).fetchone()
    if other_active is not None:
        holder = (
            other_active["session_id"]
            if hasattr(other_active, "keys")
            else other_active[0]
        )
        return RELEASE_FAILURE_NOT_OWNED, holder

    historical = conn.execute(
        f"SELECT session_id FROM work_claims WHERE {where} "
        f"ORDER BY claimed_at DESC, id DESC LIMIT 1",
        params,
    ).fetchone()
    if historical is not None:
        holder = (
            historical["session_id"]
            if hasattr(historical, "keys")
            else historical[0]
        )
        return RELEASE_FAILURE_ALREADY_TERMINAL, holder

    return RELEASE_FAILURE_ITEM_NOT_FOUND, None


def diagnose_release_miss(
    conn: Any,
    item_lookup: str,
    item_legacy: str,  # noqa: ARG001 — preserved for legacy compat
) -> tuple[str, Optional[str]]:
    """Legacy item-id form. Kept as a thin shim."""
    from .work_claim_targets import make_item_target
    if not item_lookup or not item_lookup.isdigit():
        return RELEASE_FAILURE_ITEM_NOT_FOUND, None
    return diagnose_target_release_miss(
        conn, make_item_target(int(item_lookup))
    )


def read_item_status(
    conn: Any, normalized_item_id: str,
) -> Optional[str]:
    """Best-effort current ``items.status`` lookup, ``None`` on miss."""
    if not normalized_item_id.isdigit():
        return None
    try:
        p = _p(conn)
        row = conn.execute(
            f"SELECT status FROM items WHERE id = {p}",
            (int(normalized_item_id),),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return None
    if row is None:
        return None
    return row["status"] if hasattr(row, "keys") else row[0]


def emit_target_release_failed(
    *,
    caller_session_id: str,
    target: WorkClaimTarget,
    holder_session_id: Optional[str],
    failure_reason: str,
    target_status: Optional[str],
    reason_intent: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit a single ItemClaimReleaseFailed event for a typed target."""
    item_id_for_event: Optional[str]
    if target.kind == TARGET_KIND_ITEM:
        item_id_for_event = str(target.item_id)
    elif target.kind == TARGET_KIND_EPIC_TASK:
        item_id_for_event = str(target.epic_id)
    else:
        item_id_for_event = f"process:{target.process_key}"
    context: Dict[str, Any] = {
        "item_id": item_id_for_event,
        "caller_session_id": caller_session_id,
        "holder_session_id": holder_session_id,
        "failure_reason": failure_reason,
        "target_status": target_status,
        "release_reason_intent": reason_intent,
        "target_kind": target.kind,
        "target_label": target.render(),
    }
    if target.kind == TARGET_KIND_PROCESS:
        context["process_key"] = target.process_key
        context["conflict_group"] = target.conflict_group
    if extra:
        context.update(extra)
    _sa._emit_event(
        EVENT_ITEM_CLAIM_RELEASE_FAILED,
        event_kind="system",
        event_type="session_lifecycle",
        source_type="backend",
        session_id=caller_session_id,
        item_id=item_id_for_event,
        context=context,
        outcome="failed",
        severity="WARN",
    )


def emit_release_failed(
    *,
    caller_session_id: str,
    item_id_normalized: str,
    holder_session_id: Optional[str],
    failure_reason: str,
    target_status: Optional[str],
    reason_intent: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Legacy emit shim — wraps the typed form for item targets."""
    from .work_claim_targets import make_item_target
    target = (
        make_item_target(int(item_id_normalized))
        if item_id_normalized.isdigit()
        else None
    )
    if target is None:
        # Fallback: emit raw payload if id is not numeric (extremely rare).
        context: Dict[str, Any] = {
            "item_id": item_id_normalized,
            "caller_session_id": caller_session_id,
            "holder_session_id": holder_session_id,
            "failure_reason": failure_reason,
            "target_status": target_status,
            "release_reason_intent": reason_intent,
        }
        if extra:
            context.update(extra)
        _sa._emit_event(
            EVENT_ITEM_CLAIM_RELEASE_FAILED,
            event_kind="system",
            event_type="session_lifecycle",
            source_type="backend",
            session_id=caller_session_id,
            item_id=item_id_normalized,
            context=context,
            outcome="failed",
            severity="WARN",
        )
        return
    emit_target_release_failed(
        caller_session_id=caller_session_id,
        target=target,
        holder_session_id=holder_session_id,
        failure_reason=failure_reason,
        target_status=target_status,
        reason_intent=reason_intent,
        extra=extra,
    )


__all__ = [
    "ALL_RELEASE_FAILURE_REASONS",
    "RELEASE_FAILURE_ALREADY_TERMINAL",
    "RELEASE_FAILURE_DOMAIN_ERROR",
    "RELEASE_FAILURE_ITEM_NOT_FOUND",
    "RELEASE_FAILURE_NOT_OWNED",
    "diagnose_release_miss",
    "diagnose_target_release_miss",
    "emit_release_failed",
    "emit_target_release_failed",
    "read_item_status",
]
