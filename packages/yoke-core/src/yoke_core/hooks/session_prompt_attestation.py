"""Recover a lost first-prompt stamp from a terminal hook's transcript proof.

UserPromptSubmit normally stamps ``first_user_prompt_at`` while it
registers the session. If that hook never reaches the authority, the
session keeps no stamp and reads as a probe although a person talked to
it. Stop and SessionEnd carry the client's attestation
(:data:`~yoke_contracts.hook_runner.client_facts.FIRST_USER_PROMPT_KEY`):
the native timestamp of this exact session's first operator prompt.

This policy only stamps a row that already exists. It never registers or
revives a session, never changes its lifecycle, and the stamp is
write-once, so a replayed or later attestation cannot move it. A session
with no attested prompt (a true probe) is left alone. A failed stamp is
a named refusal: it records ``SessionRegistrationRefused`` with code
``SESSION_PROMPT_STAMP_REFUSED`` and raises, so the runner's failure
marker reaches the hook's stderr while the hook still allows.
"""

from __future__ import annotations

from yoke_contracts.hook_runner.client_facts import first_user_prompt_at
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.session_registration_facts import stamp_registration_prompt
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.hooks.registration_in_process import refuse_registration
from yoke_core.hooks.types import HookDecision, Next, Outcome


class SessionPromptStampRefused(SessionError):
    """The attested first prompt could not be recorded on the session row."""


def evaluate(context) -> HookDecision:
    session_id = context.session_id or ""
    attested = first_user_prompt_at(context.payload, session_id)
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
