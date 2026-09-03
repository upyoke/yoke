"""Registered handler for reading one machine's own evidence from any seat."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.session_control.evidence_fetch import EvidenceGetRequest
from yoke_core.domain.handlers.session_messages_common import (
    domain_error,
    failure,
    numeric_actor_id,
    open_connection,
    parse,
    require_global,
)
from yoke_core.domain.session_relay_types import SessionRelayError
from yoke_core.domain.sessions_analytics import SessionError


def handle_evidence_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Ask the machine that owns a session for the tail of one of its files."""
    if invalid := require_global(request):
        return invalid
    body = parse(EvidenceGetRequest, request)
    if isinstance(body, HandlerOutcome):
        return body

    from yoke_core.domain.session_evidence_fetch import (
        evidence_fetch_result,
        request_evidence_fetch,
        wait_for_evidence_fetch,
    )
    from yoke_core.domain.session_relay_storage import utc_now

    conn = open_connection()
    try:
        record = request_evidence_fetch(
            conn,
            actor_id=numeric_actor_id(request),
            caller_session_id=str(request.actor.session_id or "").strip() or None,
            session_id=body.session_id,
            kind=body.kind,
            file_name=body.file,
            evidence_id=body.evidence_id,
            tail_lines=body.tail,
            now=utc_now(),
        )
        if body.wait_seconds <= 0:
            return HandlerOutcome(result_payload=evidence_fetch_result(record))
        return HandlerOutcome(
            result_payload=wait_for_evidence_fetch(
                conn,
                str(record["fetch_id"]),
                wait_seconds=body.wait_seconds,
            )
        )
    except (SessionError, SessionRelayError) as exc:
        conn.rollback()
        return failure(exc.code, str(exc))
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


__all__ = ["handle_evidence_get"]
