"""Reflection-capture pipeline.

The registered ``ouroboros.reflection.capture`` handler and automatic
Agent hook call this server-side parser, writer and marker dispatcher.
Manual capture uses ``yoke ouroboros reflection capture --text-file PATH``.
"""

from __future__ import annotations

import os
import hashlib
import sys
from typing import List, Optional, Tuple

from yoke_core.domain.reflection_capture_shape_parsers import (
    CANONICAL_REFLECTION_CATEGORIES,
    ReflectionEntry,
)
from yoke_core.domain.reflection_capture_shapes import CaptureResult, parse_text


# Canonical entry template surfaced inline so the capture handler (and
# any caller that imports the constant) renders the expected canonical
# shape without grepping for the regex.
CANONICAL_ENTRY_TEMPLATE = (
    "---REFLECTION-START---\n"
    "---BEGIN ENTRY---\n"
    "timestamp: 2026-05-14T12:00:00Z\n"
    "agent: engineer\n"
    "context: YOK-N task M (optional free-form)\n"
    f"category: {' | '.join(CANONICAL_REFLECTION_CATEGORIES)}\n"
    "<entry body — observation, systemic root cause, improvement>\n"
    "---END ENTRY---\n"
    "(repeat ---BEGIN ENTRY--- ... ---END ENTRY--- per reflection)\n"
    "---REFLECTION-END---"
)


def parse_reflection_blocks(
    text: str,
    *,
    default_agent: str = "unknown",
) -> Tuple[List[ReflectionEntry], List[str]]:
    """Parse all reflection entries from *text*.

    Thin wrapper over :func:`reflection_capture_shapes.parse_text` that
    preserves the legacy ``(entries, errors)`` tuple shape existing
    callers depend on. New callers should use ``parse_text`` directly
    to consume the structured :class:`CaptureResult`.
    """
    entries, result = parse_text(text, default_agent=default_agent)
    return entries, list(result.errors)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

EVENT_PERSIST_FAILED = "ReflectionCapturePersistFailed"


def _emit_persist_failed(
    *, agent: str, category: str, body: str, exc: Exception
) -> None:
    """Best-effort emission so silent persist drops become observable."""
    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            EVENT_PERSIST_FAILED,
            event_kind="hook",
            event_type="reflection_capture",
            context={
                "agent": agent,
                "category": category,
                "body_excerpt": body[:200],
                "exception_type": type(exc).__name__,
            },
            session_id=os.environ.get("YOKE_SESSION_ID", ""),
        )
    except Exception:
        pass


def persist_entries(
    entries: List[ReflectionEntry],
    *,
    project: Optional[str] = None,
    _conn=None,
) -> CaptureResult:
    """Persist parsed entries to the ouroboros_entries table.

    Returns a :class:`CaptureResult` summarising what happened.

    *_conn* is for testing only — pass an open connection to skip
    the default ``connect()`` call.
    """
    from yoke_core.domain.ouroboros import cmd_insert_entry

    result = CaptureResult(
        entries_parsed=len(entries),
        entries_persisted=0,
        entries_skipped=0,
        errors=[],
    )

    if _conn is not None:
        conn = _conn
        owns_conn = False
    else:
        from yoke_core.domain.db_helpers import connect

        conn = connect()
        owns_conn = True
    try:
        for entry in entries:
            try:
                ret = cmd_insert_entry(
                    conn,
                    timestamp=entry.timestamp,
                    agent=entry.agent,
                    context=entry.context or None,
                    category=entry.category,
                    body=entry.body,
                    project=project,
                )
                if ret == "Duplicate entry skipped":
                    result.entries_skipped += 1
                else:
                    result.entries_persisted += 1
            except Exception as exc:
                result.errors.append(
                    f"Insert failed for entry (agent={entry.agent}, "
                    f"category={entry.category}): {exc}"
                )
                _emit_persist_failed(
                    agent=entry.agent,
                    category=entry.category,
                    body=entry.body,
                    exc=exc,
                )
    finally:
        if owns_conn:
            conn.close()

    return result


# ---------------------------------------------------------------------------
# Full capture pipeline
# ---------------------------------------------------------------------------


def capture_reflections(
    text: str,
    *,
    default_agent: str = "unknown",
    project: Optional[str] = None,
    session_id: Optional[str] = None,
    _conn=None,
) -> CaptureResult:
    """Parse and persist reflection entries from subagent output.

    Calls :func:`reflection_capture_shapes.parse_text` to get the
    structured block classification and any entries the multi-shape
    parser extracted, then persists those entries via
    :func:`persist_entries`. The returned :class:`CaptureResult` carries
    both the structured block-classification fields (``blocks_seen``,
    ``blocks_unrecognized``, ``unrecognized_block_examples``, ...) and
    the legacy fields (``entries_parsed``, ``entries_persisted``, ...).
    """
    entries, result = parse_text(text, default_agent=default_agent)
    if not entries:
        return result

    persist = persist_entries(entries, project=project, _conn=_conn)
    result.entries_persisted = persist.entries_persisted
    result.entries_duplicate_skipped = persist.entries_skipped
    result.entries_persist_failed = len(persist.errors)
    result.entries_parsed = persist.entries_parsed
    result.entries_skipped = persist.entries_skipped
    result.errors.extend(persist.errors)

    from yoke_core.domain.reflection_capture_field_note import (
        dispatch_markers_for_entry,
    )

    session_id = (
        session_id if session_id is not None else os.environ.get("YOKE_SESSION_ID", "")
    )
    for entry in entries:
        dispatch_markers_for_entry(
            body=entry.body,
            agent=entry.agent,
            context=entry.context,
            session_id=session_id,
            errors=result.errors,
            project=project,
            correlation_id=hashlib.sha256(
                repr(
                    (
                        entry.timestamp,
                        entry.agent,
                        entry.context,
                        entry.category,
                        entry.body,
                    )
                ).encode()
            ).hexdigest(),
        )
    return result


if __name__ == "__main__":
    print(
        "direct_database_entrypoint_retired: retain the response text and use "
        "yoke ouroboros reflection capture --text-file PATH --project P.",
        file=sys.stderr,
    )
    sys.exit(2)
