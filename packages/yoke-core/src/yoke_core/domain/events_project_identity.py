"""Project and item identity resolution for event writes."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.events_crud import normalize_event_item_id
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none

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


def working_project_for_event(
    *,
    conn: Any = None,
    session_id: str = "",
    item_id: Optional[int] = None,
    directory: Any = None,
) -> Any:
    """Use the event's durable owner, or its mapped caller checkout.

    Server-side writers pass their connection; their process directory is
    unrelated to the caller's project. Local hooks may pass a caller directory.
    Unknown ownership remains unscoped.
    """
    if conn is not None:
        if item_id is not None:
            row = conn.execute(
                f"SELECT project_id FROM items WHERE id = {_placeholder(conn)}",
                (item_id,),
            ).fetchone()
            if row is not None:
                return _row_value(row, "project_id", 0)
        project = _session_project_id(conn, session_id) if session_id else None
        if project is not None:
            return project
    if directory is not None:
        from yoke_contracts.project_defaults import default_project_for_directory

        return default_project_for_directory(directory)
    return None


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


def _parse_envelope_mapping(envelope: Any) -> Optional[dict[str, Any]]:
    if envelope is None or envelope == "":
        return None
    if isinstance(envelope, dict):
        return envelope
    if not isinstance(envelope, str):
        return None
    try:
        parsed = json.loads(envelope)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def resolution_envelope_for_event_row(
    *,
    session_id: str,
    event_type: str,
    project: Any,
    envelope: Any = None,
) -> dict[str, Any]:
    """Build resolver input from canonical row identity plus valid context.

    Stored envelope ``session_id`` / ``event_type`` / ``project`` never
    replace the row. Parseable ``context`` still participates so explicit
    context project ids keep native writer precedence.
    """
    resolved: dict[str, Any] = {
        "session_id": session_id,
        "event_type": event_type,
        "project": project,
    }
    parsed = _parse_envelope_mapping(envelope)
    if parsed is None:
        return resolved
    context = parsed.get("context")
    if isinstance(context, dict):
        resolved["context"] = context
    return resolved


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

    # No context project, no session project: the event indexes as
    # global rather than being attributed to any particular project.
    return resolve_project_id_for_event(conn, db_path, envelope.get("project"))


def resolve_item_id_for_event(
    conn: Optional[Any],
    db_path: Optional[str],
    item_id: Any,
) -> Optional[str]:
    """Normalize an emitter's item token to the bare internal id the index stores.

    Emitters are engine code: an int or digit string is the internal id, a
    ``PREFIX-N`` ref resolves through the one item resolver, and work-unit
    sentinels normalize to ``None``. A number is never re-read as a project
    sequence.
    """
    if item_id is None or isinstance(item_id, bool):
        return None
    if isinstance(item_id, int):
        return str(item_id)
    from yoke_contracts.public_ref import parse_public_item_ref

    text = str(item_id).strip()
    prefix, sequence = parse_public_item_ref(text)
    if prefix is None or sequence is None:
        return normalize_event_item_id(text)
    if conn is not None:
        resolved = resolve_item_ref_or_none(conn, text)
        return None if resolved is None else str(resolved)
    try:
        own_conn = db_backend.connect(db_path)
    except Exception:
        return None
    try:
        resolved = resolve_item_ref_or_none(own_conn, text)
        return None if resolved is None else str(resolved)
    finally:
        own_conn.close()


__all__ = [
    "resolution_envelope_for_event_row",
    "resolve_envelope_project_id_for_event",
    "resolve_item_id_for_event",
    "resolve_project_id_for_event",
]
