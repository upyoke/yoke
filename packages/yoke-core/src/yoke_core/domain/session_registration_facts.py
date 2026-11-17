"""Durable prompt registration facts and named insert refusals."""

from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.db_savepoint import SavepointLostError


def insert_refused(exc: Exception) -> SessionError:
    constraint = getattr(getattr(exc, "diag", None), "constraint_name", None) or str(
        exc
    )
    return SessionError(
        "SESSION_INSERT_REFUSED",
        compose_refusal(
            f"Session insertion violated constraint: {constraint}.",
            recovery="repair the named registration constraint and retry the hook.",
        ),
    )


def stamp_registration_prompt(
    conn: Any, session_id: str, now: Any, first_prompt: bool
) -> None:
    if not first_prompt:
        return
    from yoke_core.domain.session_recovery_facts import stamp_first_user_prompt

    try:
        if not stamp_first_user_prompt(conn, session_id, now):
            raise ValueError("the registered session row is missing")
    except SavepointLostError:
        raise
    except Exception as exc:
        raise SessionError(
            "SESSION_PROMPT_STAMP_REFUSED",
            compose_refusal(
                f"First prompt could not be recorded: {exc}.",
                recovery="repair the session schema or row and retry UserPromptSubmit.",
            ),
        ) from exc
