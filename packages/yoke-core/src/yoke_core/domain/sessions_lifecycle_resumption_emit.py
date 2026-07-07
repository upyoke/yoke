"""``HarnessSessionResumed`` event constant, payload, and emit helper.

Sibling to :mod:`sessions_analytics_core` (registry constants live there)
and :mod:`scheduler_events` (sibling emit helpers for adjacent
reactivation events). The dedicated event surfaces the resumption
marker — a single ``event_name`` predicate is enough to
locate the episode boundary on the events ledger, so audit callers no
longer have to introspect the ``HarnessSessionStarted`` envelope to
distinguish a fresh start from a resumption.

Episode-boundary query helpers consult both ``HarnessSessionResumed``
and ``HarnessSessionStarted`` rows; see
:mod:`yoke_core.domain.events_current_episode` for the shared
resolver.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists

_logger = logging.getLogger(__name__)


EVENT_HARNESS_SESSION_RESUMED = "HarnessSessionResumed"


_REGISTRY_ROW = (
    EVENT_HARNESS_SESSION_RESUMED,
    "system",
    "session_lifecycle",
    "yoke_core.domain.sessions_lifecycle_resumption_emit",
    (
        "Emitted by register_session reactivation when the prior release "
        "carried release_reason='session_ended' AND at least one prior "
        "session_ended claim is surfaced. Marks the start of a new "
        "episode for a session_id that legitimately spans episodes. "
        "Carries session_id, prior_release_reason, released_claim_count, "
        "reacquired_count, conflict_count, claim_details with per-target "
        "episode_scope tags (inherited|reacquired|conflict). Queryable "
        "with a single event_name predicate so --current-episode boundary "
        "resolution is O(1)."
    ),
    "INFO",
)


def ensure_registry_entry(conn: Any) -> None:
    """Insert the ``HarnessSessionResumed`` registry row if absent."""
    try:
        if not _table_exists(conn, "event_registry"):
            return
        name, kind, etype, service, desc, severity = _REGISTRY_ROW
        conn.execute(
            "INSERT INTO event_registry ("
            "event_name, event_kind, event_type, owner_service, "
            "description, context_schema, severity_default, status"
            ") VALUES (%s, %s, %s, %s, %s, NULL, %s, 'active') "
            "ON CONFLICT(event_name) DO NOTHING",
            (name, kind, etype, service, desc, severity),
        )
        conn.commit()
    except db_backend.database_error_types(conn):
        return


def build_claim_details(
    *,
    released_claims: Sequence[Mapping[str, Any]],
    reacquired_claims: Sequence[Mapping[str, Any]],
    conflicts: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Render claim entries with explicit ``episode_scope`` tags.

    Order: inherited (released-but-not-reacquired) -> reacquired ->
    conflicts. Each entry carries the original target descriptor plus
    the scope label so audit callers can tell why a claim is in the
    current episode without joining against the work_claims table.
    """
    def _key(entry: Mapping[str, Any]):
        return (
            entry.get("target_kind"),
            entry.get("item_id"),
            entry.get("epic_id"),
            entry.get("task_num"),
            entry.get("process_key"),
            entry.get("conflict_group"),
        )

    reacquired_index = {_key(e): e for e in reacquired_claims}
    conflict_index = {_key(e): e for e in conflicts}

    details: List[Dict[str, Any]] = []
    for entry in released_claims:
        key = _key(entry)
        if key in reacquired_index:
            scope = "reacquired"
            extra = {
                k: v
                for k, v in reacquired_index[key].items()
                if k == "new_claim_id"
            }
        elif key in conflict_index:
            scope = "conflict"
            extra = {
                k: v
                for k, v in conflict_index[key].items()
                if k not in entry
            }
        else:
            scope = "inherited"
            extra = {}
        details.append({**dict(entry), "episode_scope": scope, **extra})

    existing_keys = {_key(d) for d in details}
    for entry in reacquired_claims:
        if _key(entry) in existing_keys:
            continue
        details.append({**dict(entry), "episode_scope": "reacquired"})
        existing_keys.add(_key(entry))

    for entry in conflicts:
        if _key(entry) in existing_keys:
            continue
        details.append({**dict(entry), "episode_scope": "conflict"})
        existing_keys.add(_key(entry))

    return details


def emit_session_resumed(
    *,
    session_id: str,
    released_claims: Sequence[Mapping[str, Any]],
    reacquired_claims: Sequence[Mapping[str, Any]],
    conflicts: Sequence[Mapping[str, Any]],
    prior_release_reason: str = "session_ended",
    project: str = "yoke",
) -> Optional[int]:
    """Emit ``HarnessSessionResumed`` for a resumed-episode register pass.

    Returns the inserted event id on success, ``None`` on emission
    failure (telemetry is best-effort and never blocks the register
    path). The envelope keys are stable so audit consumers can rely on
    them.
    """
    try:
        from .db_helpers import connect
        from .events import emit_event

        try:
            seed_conn = connect()
            try:
                ensure_registry_entry(seed_conn)
            finally:
                seed_conn.close()
        except Exception as seed_exc:
            _logger.debug(
                "%s registry seed skipped: %s",
                EVENT_HARNESS_SESSION_RESUMED,
                seed_exc,
            )

        context: Dict[str, Any] = {
            "session_id": session_id,
            "resumption": True,
            "prior_release_reason": prior_release_reason,
            "released_claim_count": len(released_claims),
            "reacquired_count": len(reacquired_claims),
            "conflict_count": len(conflicts),
            "claim_details": build_claim_details(
                released_claims=released_claims,
                reacquired_claims=reacquired_claims,
                conflicts=conflicts,
            ),
        }
        emit_event(
            EVENT_HARNESS_SESSION_RESUMED,
            event_kind="system",
            event_type="session_lifecycle",
            source_type="backend",
            session_id=session_id,
            project=project,
            context=context,
        )
    except Exception as exc:
        _logger.debug("%s emission failed: %s", EVENT_HARNESS_SESSION_RESUMED, exc)
        return None
    return None


__all__ = [
    "EVENT_HARNESS_SESSION_RESUMED",
    "build_claim_details",
    "emit_session_resumed",
    "ensure_registry_entry",
]
