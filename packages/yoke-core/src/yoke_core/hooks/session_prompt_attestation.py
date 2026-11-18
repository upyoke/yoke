"""Recover a lost first-prompt stamp from a terminal hook's transcript proof.

UserPromptSubmit normally stamps ``first_user_prompt_at`` while it
registers the session. If that hook never reaches the authority, the
session keeps no stamp and reads as a probe although a person talked to
it. Stop and SessionEnd carry the client's attestation
(:data:`~yoke_contracts.hook_runner.client_facts.FIRST_USER_PROMPT_KEY`):
either the prompt's native timestamp or evidence to derive it from SessionEnd.

This policy only stamps a row that already exists. It never registers or
revives a session, never changes its lifecycle, and the stamp is
write-once, so a replayed or later attestation cannot move it. A session
with no attested prompt (a true probe) is left alone. A failed stamp is
a named refusal: it records ``SessionRegistrationRefused`` with code
``SESSION_PROMPT_STAMP_REFUSED`` and raises, so the runner's failure
marker reaches the hook's stderr while the hook still allows.
"""

from __future__ import annotations

from datetime import timedelta

from yoke_contracts.hook_observation_age import observed_at
from yoke_contracts.hook_runner.client_facts import (
    FIRST_USER_PROMPT_KEY,
    first_user_prompt_at,
    read_client_fact,
)
from yoke_contracts.timestamps import format_instant
from yoke_core.domain.events import emit_event
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.session_registration_facts import stamp_registration_prompt
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.hooks.registration_in_process import refuse_registration
from yoke_core.hooks.types import HookDecision, Next, Outcome


class SessionPromptStampRefused(SessionError):
    """The attested first prompt could not be recorded on the session row."""


_SKIP_DIAGNOSTICS = {
    "transcript_unavailable": "Check that the SessionEnd hook can read its transcript.",
    "no_user_row": "Check the transcript for a top-level user row within the scan bound.",
    "missing_duration_ms": "Check that the SessionEnd payload includes duration_ms.",
    "invalid_duration_ms": "Check that SessionEnd reports a valid duration in milliseconds.",
    "missing_end_time": "Check that the SessionEnd hook has an observation time.",
}


def _record_skip(context, session_id: str, reason: str) -> None:
    emit_event(
        "SessionPromptAttestationSkipped",
        event_kind="system",
        event_type="session_prompt_attestation",
        source_type="hook",
        session_id=session_id,
        outcome="skipped",
        hook_event_name=context.event_name,
        context={"reason": reason, "recovery": _SKIP_DIAGNOSTICS[reason]},
    )


def _session_end_prompt_at(context, session_id: str) -> str | None:
    if context.event_name != "SessionEnd" or not session_id:
        return None
    fact = read_client_fact(context.payload, FIRST_USER_PROMPT_KEY)
    if not isinstance(fact, dict) or fact.get("session_id") != session_id:
        return None
    reason = fact.get("skip_reason")
    if isinstance(reason, str) and reason in _SKIP_DIAGNOSTICS:
        _record_skip(context, session_id, reason)
        return None
    if "duration_ms" not in fact:
        return None
    duration_ms = fact["duration_ms"]
    if type(duration_ms) is not int or duration_ms < 0:
        _record_skip(context, session_id, "invalid_duration_ms")
        return None
    if context.now is None:
        _record_skip(context, session_id, "missing_end_time")
        return None
    end = observed_at(context.payload, context.now) or context.now
    try:
        return format_instant(end - timedelta(milliseconds=duration_ms))
    except OverflowError:
        _record_skip(context, session_id, "invalid_duration_ms")
        return None


def evaluate(context) -> HookDecision:
    session_id = context.session_id or ""
    attested = first_user_prompt_at(context.payload, session_id)
    if attested is None:
        attested = _session_end_prompt_at(context, session_id)
    if attested is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    conn = connect()
    try:
        try:
            stamp_registration_prompt(conn, session_id, attested, True)
            conn.commit()
        except SessionError as exc:
            refuse_registration(session_id, exc.code, str(exc), conn=conn)
            raise SessionPromptStampRefused(exc.code, str(exc)) from exc
    finally:
        conn.close()
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


__all__ = ["SessionPromptStampRefused", "evaluate"]
