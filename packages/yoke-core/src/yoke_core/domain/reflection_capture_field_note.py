"""PM/PD field-note bridge for `reflection_capture`.

Non-Bash subagents (Product Manager, Product Designer) fire field-notes
by including a ``field_note_kind: failed|new|unclear`` marker line
inside their reflection entry body. The PostToolUse Agent-tool hook
(:mod:`yoke_core.domain.reflection_capture_hook`) captures the
reflection block via ``capture_reflections``; this module then converts
each recognized marker into one ``ouroboros.field_note.append``
function call dispatched in-process through the canonical Yoke
function-call surface (no new HTTP path).

Invalid marker values (anything outside the closed enum)
emit a structured ``ReflectionMarkerParseFailed`` event so operators can
surface stale PM/PD body teaching, and the field-note is NOT fired.
The reflection text itself is captured as plain entry body by the main
parser; this module only governs the field-note side effect.
"""

from __future__ import annotations

import re
import uuid
from typing import List, Optional

from yoke_core.domain import events as _events
from yoke_core.domain.handlers.ouroboros_field_note import (
    FIELD_NOTE_KIND_VALUES,
)


# Marker recognized inside any reflection entry body line. Tolerant of
# leading/trailing whitespace and arbitrary case on the keyword; the
# value is normalised to lowercase for enum comparison.
_MARKER_RE = re.compile(
    r"^\s*field_note_kind\s*:\s*([A-Za-z_][A-Za-z0-9_-]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

PARSE_FAILED_EVENT_NAME = "ReflectionMarkerParseFailed"
MARKER_EVIDENCE_PREVIEW_CHARS = 200


def _evidence_preview(body: str) -> str:
    """Return a short preview suitable for field-note evidence."""
    return body.strip()[:MARKER_EVIDENCE_PREVIEW_CHARS]


def find_markers(text: str) -> List[str]:
    """Return every ``field_note_kind`` raw value in *text*, in order.

    Values are NOT validated here — invalid kinds are surfaced by
    :func:`dispatch_markers` so the recovery path can emit the
    structured ``ReflectionMarkerParseFailed`` event with full context.
    """
    return [m.group(1).strip().lower() for m in _MARKER_RE.finditer(text)]


def _emit_parse_failed(
    *,
    raw_value: str,
    agent: str,
    context: str,
    session_id: str,
    body_preview: str,
) -> None:
    """Emit a non-fatal ``ReflectionMarkerParseFailed`` event."""
    _events.emit_event(
        PARSE_FAILED_EVENT_NAME,
        event_kind="domain",
        event_type="reflection_marker_parse_failed",
        source_type="agent",
        session_id=session_id,
        severity="WARN",
        outcome="parse_failed",
        agent=agent,
        context={
            "raw_value": raw_value,
            "valid_values": list(FIELD_NOTE_KIND_VALUES),
            "agent": agent,
            "entry_context": context,
            "body_preview": body_preview,
        },
    )


def _dispatch_field_note(
    *,
    kind: str,
    evidence: str,
    session_id: str,
    correlation_id: Optional[str],
    project: Optional[str] = None,
    agent: Optional[str] = None,
) -> Optional[str]:
    """Dispatch one ``ouroboros.field_note.append``; return its refusal, if any.

    The call carries the capturing session when one is known; otherwise the
    dispatcher binds this universe's operating actor or refuses
    ``actor_required``.
    """
    from yoke_core.domain.handlers.__init_register__ import (
        register_all_handlers,
    )
    from yoke_core.domain.yoke_function_dispatch import dispatch
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )

    # Idempotent registration — the registry refuses duplicates safely.
    try:
        register_all_handlers()
    except Exception:
        # Registration races (e.g. already-registered) are non-fatal here;
        # the dispatcher surfaces real handler-missing errors below.
        pass

    payload = {"kind": kind, "evidence": evidence}
    if correlation_id:
        payload["correlation_id"] = correlation_id
    if project:
        payload["project"] = project
    if agent:
        payload["actor_role"] = agent

    request = FunctionCallRequest(
        function="ouroboros.field_note.append",
        request_id=str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                repr((session_id, project, correlation_id, kind, evidence)),
            )
        ),
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="global"),
        payload=payload,
    )
    response = dispatch(request, ambient_session_id=session_id or None)
    if response.success:
        return None
    error = response.error
    code = error.code if error is not None else "dispatch_failed"
    message = error.message if error is not None else "no error detail returned"
    return f"field-note {kind!r} not recorded: {code}: {message}"


def dispatch_markers_for_entry(
    *,
    body: str,
    agent: str,
    context: str,
    session_id: str,
    correlation_id: Optional[str] = None,
    errors: Optional[List[str]] = None,
    project: Optional[str] = None,
) -> int:
    """Process every field-note marker found in one reflection entry.

    Recognized markers dispatch ``ouroboros.field_note.append`` with
    the entry body as evidence. Invalid markers emit
    ``ReflectionMarkerParseFailed`` and are skipped (no field-note).

    Returns the number of field-notes successfully dispatched. The
    function never raises — field-note dispatch is follow-on work and must
    not block reflection capture itself — but every refused or failed
    dispatch is appended to ``errors`` so the capture reports it.
    """
    if not body:
        return 0
    dispatched = 0
    evidence = _evidence_preview(body)
    for raw_value in find_markers(body):
        if raw_value in FIELD_NOTE_KIND_VALUES:
            try:
                refusal = _dispatch_field_note(
                    kind=raw_value,
                    evidence=evidence,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    project=project,
                    agent=agent,
                )
            except Exception as exc:  # noqa: BLE001 - reported, never raised
                refusal = f"field-note {raw_value!r} dispatch failed: {exc!r}"
            if refusal is None:
                dispatched += 1
            elif errors is not None:
                errors.append(refusal)
        else:
            if errors is not None:
                errors.append(
                    f"reflection_marker_invalid: field_note_kind {raw_value!r}; "
                    f"use one of {', '.join(FIELD_NOTE_KIND_VALUES)} and retry capture"
                )
            try:
                _emit_parse_failed(
                    raw_value=raw_value,
                    agent=agent,
                    context=context,
                    session_id=session_id,
                    body_preview=evidence,
                )
            except Exception:
                pass
    return dispatched


__all__ = [
    "MARKER_EVIDENCE_PREVIEW_CHARS",
    "PARSE_FAILED_EVENT_NAME",
    "dispatch_markers_for_entry",
    "find_markers",
]
