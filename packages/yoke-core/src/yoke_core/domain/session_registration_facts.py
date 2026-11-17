"""Durable prompt registration facts and named insert refusals."""

from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.sessions_analytics import SessionError


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
    from yoke_core.domain.db_helpers import instant_parameter
    from yoke_core.domain import db_backend

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        cursor = conn.execute(
            "UPDATE harness_sessions SET first_user_prompt_at = "
            f"COALESCE(first_user_prompt_at, {p}) WHERE session_id = {p}",
            (instant_parameter(conn, now), session_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("the registered session row is missing")
    except Exception as exc:
        raise SessionError(
            "SESSION_PROMPT_STAMP_REFUSED",
            compose_refusal(
                f"First prompt could not be recorded: {exc}.",
                recovery="repair the session schema or row and retry UserPromptSubmit.",
            ),
        ) from exc
