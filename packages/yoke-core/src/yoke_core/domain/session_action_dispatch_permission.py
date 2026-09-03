"""Apply the session-action role check inside dispatcher authorization.

``session_control.*`` classifies as ``ACTOR_SESSION`` — a caller acting on
its own session needs no tenant target — but most of that family acts on
*somebody else's* session, and that is tenant work with a role behind it.
This adapter is where the two meet: for the calls whose payload names the
target outright it resolves that session's project, asks
:mod:`yoke_core.domain.session_action_authority` the one question, and
turns a refusal into the dispatcher's own response shape. Every other
``ACTOR_SESSION`` call passes through exactly as before.

A target the payload does not name (a message fanned out by audience, a
wake addressed by item ref) is resolved by its handler, which applies the
same authority per project it resolved — so the check is not skipped
there, it is applied where the recipients are actually known.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.function_unresolved_project import (
    permission_error_response as _error_response,
)
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.session_action_authority import (
    DIRECTLY_TARGETED_FUNCTIONS,
    authorize_session_action,
)
from yoke_core.domain.yoke_function_permission_types import DispatchPermission
from yoke_core.domain.yoke_function_registry import RegistryEntry


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def target_session_row(conn: Any, session_id: str) -> Optional[dict[str, Any]]:
    """Return the target's ``session_id``/``project_id``/``actor_id``, or None."""
    try:
        row = conn.execute(
            "SELECT session_id, project_id, actor_id FROM harness_sessions "
            f"WHERE session_id = {_p(conn)}",
            (session_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — an unreadable row defers to the handler
            pass
        return None
    if row is None:
        return None
    keys = ("session_id", "project_id", "actor_id")
    if hasattr(row, "get"):
        return {key: row.get(key) for key in keys}
    return dict(zip(keys, row))


def session_action_dispatch_permission(
    conn: Any,
    entry: RegistryEntry,
    request: FunctionCallRequest,
    actor_id: int,
    permission_key: Optional[str],
) -> DispatchPermission:
    """Authorize a directly targeted session action; pass everything else."""
    if entry.function_id not in DIRECTLY_TARGETED_FUNCTIONS:
        return DispatchPermission(permission_key, None, None)
    target_session_id = str((request.payload or {}).get("session_id") or "").strip()
    if not target_session_id:
        return DispatchPermission(permission_key, None, None)
    target = target_session_row(conn, target_session_id)
    # An unknown session is the handler's not-found to report, with the
    # target name in it; refusing here would answer a different question.
    if target is None or target.get("project_id") is None:
        return DispatchPermission(permission_key, None, None)
    project_id = int(target["project_id"])
    decision = authorize_session_action(
        conn,
        actor_id=actor_id,
        function_id=entry.function_id,
        project_id=project_id,
        target=target,
    )
    if decision.allowed:
        return DispatchPermission(decision.permission_key, project_id, None)
    return DispatchPermission(
        decision.permission_key,
        project_id,
        None,
        error=_error_response(request, entry, "permission_denied", decision.message),
    )


__all__ = ["session_action_dispatch_permission", "target_session_row"]
