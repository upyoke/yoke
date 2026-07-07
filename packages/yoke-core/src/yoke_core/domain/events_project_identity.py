"""Project and item identity resolution for event writes."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.events_crud import normalize_event_item_id
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yok_n_parser import parse_item_id

GLOBAL_EVENT_PROJECT_TOKENS = {"", "all", "global", "multi"}
SESSION_SCOPED_EVENT_TYPES = {
    "hook_dispatch",
    "hook_execution_failure",
    "hook_guardrail_evaluated",
    "session_hook_failure",
    "session_lifecycle",
    "tool_call",
}


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]


def _rollback(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    try:
        conn.rollback()
    except Exception:
        pass


def _context_project_id(envelope: dict[str, Any]) -> Optional[int]:
    context = envelope.get("context")
    if not isinstance(context, dict):
        return None
    candidates = [context.get("project_id")]
    detail = context.get("detail")
    if isinstance(detail, dict):
        candidates.append(detail.get("project_id"))
    for value in candidates:
        if value in (None, ""):
            continue
        try:
            project_id = int(value)
        except (TypeError, ValueError):
            continue
        if project_id > 0:
            return project_id
    return None


def _session_project_id(conn: Any, session_id: str) -> Optional[int]:
    try:
        row = conn.execute(
            "SELECT project_id FROM harness_sessions "
            f"WHERE session_id = {_placeholder(conn)}",
            (session_id,),
        ).fetchone()
    except Exception:
        _rollback(conn)
        return None
    if row is None:
        return None
    try:
        project_id = int(_row_value(row, "project_id", 0))
    except (TypeError, ValueError):
        return None
    return project_id if project_id > 0 else None


def resolve_project_id_for_event(
    conn: Optional[Any],
    db_path: Optional[str],
    project: Any,
) -> Optional[int]:
    """Resolve the boundary project token to ``projects.id`` for writes."""
    if project is None or str(project).strip().lower() in GLOBAL_EVENT_PROJECT_TOKENS:
        return None
    # An unresolvable project token indexes the event as global (NULL
    # project) rather than guessing an id: a universe without the named
    # project row (e.g. a fresh install before onboarding) must still
    # accept every event write.
    if conn is not None:
        try:
            return resolve_project_id(conn, project)
        except Exception:
            _rollback(conn)
            return None
    try:
        own_conn = db_backend.connect(db_path)
    except Exception:
        return None
    try:
        return resolve_project_id(own_conn, project)
    except Exception:
        return None
    finally:
        own_conn.close()


def resolve_envelope_project_id_for_event(
    conn: Any,
    db_path: Optional[str],
    envelope: dict[str, Any],
) -> Optional[int]:
    """Resolve the indexed project id for an already-built event envelope."""
    context_project_id = _context_project_id(envelope)
    if context_project_id is not None:
        return resolve_project_id_for_event(conn, db_path, context_project_id)

    session_id = str(envelope.get("session_id") or "").strip()
    event_type = str(envelope.get("event_type") or "").strip()
    if (
        session_id
        and session_id != "unknown"
        and event_type in SESSION_SCOPED_EVENT_TYPES
    ):
        project_id = _session_project_id(conn, session_id)
        if project_id is not None:
            return resolve_project_id_for_event(conn, db_path, project_id)

    return resolve_project_id_for_event(
        conn, db_path, envelope.get("project", "yoke")
    )


def resolve_item_id_for_event(
    conn: Optional[Any],
    db_path: Optional[str],
    item_id: Optional[str],
    *,
    project: Any,
) -> Optional[str]:
    """Resolve public item refs to internal ids; leave work-unit sentinels alone."""
    if item_id is None:
        return None
    if project is None or str(project).strip().lower() in GLOBAL_EVENT_PROJECT_TOKENS:
        return normalize_event_item_id(item_id)
    if conn is not None:
        try:
            return str(parse_item_id(item_id, project=project, conn=conn))
        except Exception:
            return normalize_event_item_id(item_id)
    try:
        own_conn = db_backend.connect(db_path)
    except Exception:
        return normalize_event_item_id(item_id)
    try:
        return str(parse_item_id(item_id, project=project, conn=own_conn))
    except Exception:
        return normalize_event_item_id(item_id)
    finally:
        own_conn.close()


__all__ = [
    "resolve_envelope_project_id_for_event",
    "resolve_item_id_for_event",
    "resolve_project_id_for_event",
]
