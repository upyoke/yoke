"""Tell the sessions the provider stopped to keep going.

Whether a session is owed a resume, and when, is settled in
``session_vendor_error_states``; this module does the telling. It runs on
the relay's ordinary poll, resumes the sessions marked ``due`` through the
same explicit stopped-route wake an operator would use, and records what
it did — including which client build the resumed turn runs on, because
the incident this exists for was cured by a client update mid-outage and
"which binary served the retry" is the first thing an operator asks.

Injection is the only side effect. A resume that the wake path refuses is
named and left for the next poll rather than retried here, and it does not
consume an attempt, because nothing reached the session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import utc_now
from yoke_core.domain.session_vendor_error_states import (
    EVENT_SESSION_VENDOR_ERROR_RESUMED,
    RESUME_BACKOFF_SECONDS,
    vendor_error_states,
)


#: Most resumes one poll will request. A provider outage stops every
#: session on the machine at once, and paying that all in one poll is how
#: the poll that owed the relay its next wake times out instead.
MAX_RESUMES_PER_POLL = 5


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _emit_resumed(
    conn: Any,
    state: Mapping[str, Any],
    *,
    installed_version: str,
    previous_version: str,
    message_id: str,
) -> None:
    from yoke_core.domain.events import emit_event

    session_id = str(state.get("session_id") or "")
    emit_event(
        EVENT_SESSION_VENDOR_ERROR_RESUMED,
        event_kind="system",
        event_type="session_lifecycle",
        source_type="backend",
        session_id=session_id,
        context={
            "session_id": session_id,
            "signature_id": state.get("signature_id"),
            "error_message": state.get("error_message"),
            "observed_at": state.get("observed_at"),
            "attempt": int(state.get("attempts") or 0) + 1,
            "budget": state.get("budget"),
            "message_id": message_id,
            # The binary the resumed turn actually runs on. The provider's
            # refusal was cured by a client update mid-incident, so which
            # build served the retry is the first thing an operator asks.
            "executor_version": installed_version,
            "previous_executor_version": previous_version,
        },
        conn=conn,
    )


def _installed_version(
    conn: Any,
    state: Mapping[str, Any],
    *,
    machine_id: str,
    now: datetime,
) -> str:
    """The version of this surface the machine reports having right now.

    Not the version recorded when the session started: a client can be
    replaced under a running fleet, and the resume runs whichever binary
    is installed at the moment it spawns.
    """
    from yoke_core.domain.session_relay_machine_versions import (
        connected_relay_routes,
        machine_surface_versions,
    )

    versions = machine_surface_versions(
        connected_relay_routes(conn, now=now),
        machine_id=machine_id,
        project_id=state.get("project_id"),
    )
    return str(versions.get(str(state.get("executor_surface") or "")) or "")


def _resume_notice(state: Mapping[str, Any]) -> str:
    """The body the resumed worker reads first.

    It names the failure because the worker has no other way to learn why
    its turn ended, and it points at the worker's own committed state
    because that — not this notice — is the authority on where to resume.
    """
    return (
        "Your previous turn did not end on your own work: the model "
        f"provider ended it with {state.get('error_message')!r} "
        f"(classified {state.get('signature_id')}). Nothing about your item, "
        "lane, or claim changed. Continue from your last committed state: "
        "check `git log` and `git status` in your lane, re-read the item's "
        "Progress Log for where you were, and carry on. If the same failure "
        f"repeats, this resume is attempt {int(state.get('attempts') or 0) + 1} "
        f"of {state.get('budget')} before the seat is asked to step in."
    )


def resume_vendor_error_sessions(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    actor_id: int,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Resume the sessions whose backoff has elapsed; name every refusal.

    Each resume goes through the ordinary explicit stopped-route wake, so
    it inherits that path's route qualification, its one-wake-in-flight
    guard, and its delivery record — this module decides *whether* to
    resume, never how. A refusal from that path is reported by name and
    left for the next poll rather than retried here, and it does not
    consume an attempt: nothing reached the session.
    """
    from yoke_core.domain.session_manual_wake import request_session_wake
    from yoke_core.domain.session_message_types import SessionMessageError

    current = now or utc_now()
    states = vendor_error_states(
        conn,
        machine_id=machine_id,
        authorized_projects=authorized_projects,
        now=current,
    )
    due = [state for state in states if state["status"] == "due"]
    resumed: List[str] = []
    refused: List[Dict[str, Any]] = []
    for state in due[:MAX_RESUMES_PER_POLL]:
        session_id = str(state["session_id"])
        installed = _installed_version(conn, state, machine_id=machine_id, now=current)
        try:
            result = request_session_wake(
                conn,
                actor_id=actor_id,
                caller_session_id=None,
                session_id=session_id,
                public_ref=None,
                prompt=_resume_notice(state),
                now=current,
            )
        except SessionMessageError as exc:
            refused.append(
                {
                    "session_id": session_id,
                    "status": exc.code,
                    "detail": str(exc),
                }
            )
            continue
        previous = str(state.get("executor_version") or "")
        if installed and installed != previous:
            # The resumed turn runs the installed binary, so the session's
            # recorded version is now wrong in a way later version-gated
            # routing would read. Correct it with the resume that caused it.
            marker = _p(conn)
            conn.execute(
                "UPDATE harness_sessions SET executor_version="
                f"{marker} WHERE session_id={marker}",
                (installed, session_id),
            )
        _emit_resumed(
            conn,
            state,
            installed_version=installed,
            previous_version=previous,
            message_id=str(result.get("message_id") or ""),
        )
        conn.commit()
        resumed.append(session_id)
    return {
        "resumed": resumed,
        "refused": refused,
        "states": states,
        "deferred": max(0, len(due) - MAX_RESUMES_PER_POLL),
    }


__all__ = [
    "EVENT_SESSION_VENDOR_ERROR_RESUMED",
    "MAX_RESUMES_PER_POLL",
    "RESUME_BACKOFF_SECONDS",
    "resume_vendor_error_sessions",
]
