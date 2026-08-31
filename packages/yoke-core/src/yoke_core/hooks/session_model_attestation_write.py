"""Write what a harness transcript proves a session is being served.

The served columns on ``harness_sessions`` are filled here and nowhere
else on the hook path: registration stamps the request, and this runs from
every later hook, once generation has produced a transcript that names a
model. Split out of :mod:`yoke_core.hooks.service_client`, whose other
functions are all subprocess/path plumbing — this is the one that opens
the database directly.
"""

from __future__ import annotations


def attest_served_model_facts(
    session_id: str,
    transcript_path: str,
    *,
    hook_source: str = "",
) -> bool:
    """Record what the transcript proves this session is being served.

    The earliest hook that fires after generation starts is the first
    moment the transcript names a served model, so this runs from every
    later hook and writes whatever the artifact now proves. It is the
    write path for the served columns; the requested ones are stamped at
    registration and are never touched here.

    No-ops when the transcript attests nothing, when the row already says
    the same thing, or when the DB / schema / session row is unavailable.
    A later reading replaces an earlier one — a session that switched
    model or effort mid-run is currently serving the newer value.

    Emits ``HarnessSessionModelRefreshed`` when a write fires, so which
    hook surface attested and when is answerable from stored rows.

    Returns True when an UPDATE fired, False otherwise.
    """
    if not session_id or not transcript_path:
        return False
    try:
        from yoke_harness.model_attestation import attest_served_facts

        served = attest_served_facts(
            "claude-code", {}, transcript_path=transcript_path
        )
    except Exception:
        return False
    if not served.attested():
        return False

    try:
        from yoke_core.domain import db_backend
        from yoke_core.domain.session_model_columns import (
            MODEL_COLUMNS,
            changed_columns,
        )

        conn = db_backend.connect(busy_timeout_ms=2000)
    except Exception:
        return False
    previous_model = ""
    try:
        row = conn.execute(
            "SELECT " + ", ".join(MODEL_COLUMNS) + " FROM harness_sessions "
            "WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        if row is None:
            return False
        previous_model = row["model"] or ""
        columns, values = changed_columns(row, served)
        if not columns:
            return False
        assignments = ", ".join(f"{column} = %s" for column in columns)
        conn.execute(
            f"UPDATE harness_sessions SET {assignments} WHERE session_id = %s",
            (*values, session_id),
        )
        conn.commit()
    except Exception:
        return False
    finally:
        conn.close()

    try:
        from yoke_core.domain.events import emit_event as _native_emit

        _native_emit(
            "HarnessSessionModelRefreshed",
            event_kind="system",
            event_type="session_lifecycle",
            source_type="hook",
            severity="INFO",
            outcome="completed",
            session_id=session_id,
            project="yoke",
            context={
                "previous_model": previous_model,
                "refreshed_model": served.model or "",
                "hook_source": hook_source or "unknown",
            },
        )
    except Exception:
        pass
    return True


__all__ = ["attest_served_model_facts"]
