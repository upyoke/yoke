"""Write and confirm what a harness artifact proves a session is being served.

Local transcript refreshes write here; relayed facts use active-registration
healing. Both paths confirm the durable row here before a client stops reading
its artifact. Split out of :mod:`yoke_core.hooks.service_client`, whose other
functions are subprocess/path plumbing.
"""

from __future__ import annotations

from typing import Any


def confirmed_served_model(
    session_id: Any,
    expected_model: Any,
    *,
    conn: Any = None,
) -> str | None:
    """Return the expected model only when the control-plane row holds it.

    A relayed client uses this value as its durable-write receipt.  Missing
    rows, unavailable authorities, and a different stored model all return
    ``None`` so the client keeps resolving and sending its artifact evidence.
    """
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    if not isinstance(expected_model, str) or not expected_model.strip():
        return None
    owned = conn is None
    try:
        if owned:
            from yoke_core.domain import db_helpers

            conn = db_helpers.connect()
        from yoke_core.domain import db_backend

        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT model FROM harness_sessions WHERE session_id = {marker}",
            (session_id.strip(),),
        ).fetchone()
        stored = row.get("model") if hasattr(row, "get") else row[0] if row else None
        return expected_model if stored == expected_model else None
    except Exception:
        return None
    finally:
        if owned and conn is not None:
            conn.close()


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
    direct write path for the served columns; relayed evidence heals them
    through registration. The requested columns are never touched here.

    No-ops when the transcript attests nothing, when the row already says
    the same thing, or when the DB / schema / session row is unavailable.
    A later reading replaces an earlier one — a session that switched
    model or effort mid-run is currently serving the newer value.

    Emits ``HarnessSessionModelRefreshed`` when a write fires, so which
    hook surface attested and when is answerable from stored rows.

    This is the direct transcript write path; relayed facts use duplicate-
    registration healing. Returns True when an UPDATE fired, False otherwise.
    """
    if not session_id or not transcript_path:
        return False
    try:
        from yoke_harness.model_attestation import attest_served_facts

        # The session id is not decoration here: Claude's served window
        # lives in the status line recording keyed by it, not in the
        # transcript, so a reader that passed only the transcript would
        # attest the model and silently drop the window.
        served = attest_served_facts(
            "claude-code",
            {"session_id": session_id},
            transcript_path=transcript_path,
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


__all__ = ["attest_served_model_facts", "confirmed_served_model"]
