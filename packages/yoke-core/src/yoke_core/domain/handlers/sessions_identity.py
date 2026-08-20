"""Registered read-back of the calling session's resolved identity.

Identity is resolved once, at registration: ``register_session`` stores the
canonical executor id and its display alias, the provider, the model
SessionStart observed, the execution lane the project's routing policy maps
that executor to, the workspace, the project, and the actor. This handler
reads those stored facts back through the shared projection and adds the two
policy values derived from them — the downstream paths the session's lane may
execute, and the chain budget the autonomous loop honors.

Nothing here re-derives, so nothing returned is advisory. A caller that
cannot reach the authority is refused with its recovery command rather than
handed a locally guessed value: a lane, model, or executor invented on the
client disagrees with the row every other surface reads, and a wrong value
that looks authoritative is harder to catch than a missing one — the caller
reasons correctly from a false input and nothing downstream misbehaves.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome

from yoke_core.domain.handlers.sessions_orchestration import (
    _connect_rw,
    _err,
    _session_id,
)


class IdentityRequest(BaseModel):
    pass


class IdentityResponse(BaseModel):
    session_id: str
    executor: str
    executor_display_name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    execution_lane: Optional[str] = None
    lane_allowed_paths: List[str] = []
    workspace: Optional[str] = None
    project_id: Optional[int] = None
    project_slug: Optional[str] = None
    actor_id: Optional[int] = None
    actor_label: Optional[str] = None
    mode: Optional[str] = None
    max_chain_steps: int


def _project_slug(conn: Any, project_id: Optional[int]) -> Optional[str]:
    if project_id is None:
        return None
    from yoke_core.domain.sessions_identity_read import _p

    row = conn.execute(
        f"SELECT slug FROM projects WHERE id = {_p(conn)}",
        (project_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def _actor_label(conn: Any, actor_id: Optional[int]) -> Optional[str]:
    if actor_id is None:
        return None
    from yoke_core.domain.actor_display import actor_display_name
    from yoke_core.domain.actors import (
        ActorLabelAmbiguous,
        ActorLabelMissing,
        ActorNotFound,
    )

    try:
        return actor_display_name(conn, actor_id)
    except (ActorNotFound, ActorLabelMissing, ActorLabelAmbiguous):
        return f"actor {actor_id}"


def _lane_allowed_paths(
    conn: Any, project_id: Optional[int], lane: Optional[str],
) -> List[str]:
    """Return the downstream paths ``lane`` may execute for this project.

    Routing policy lives in the project's ``session-routing`` capability with
    machine config as the no-project fallback — the same pair the offer path
    reads, so the paths reported here are the paths the scheduler applies.
    """
    if not lane:
        return []
    from yoke_core.api.routing_config import (
        load_project_routing_settings,
        load_routing_config,
    )
    from yoke_core.api.service_client_shared import _get_config_path

    routing_config = load_routing_config(
        _get_config_path(),
        project_settings=load_project_routing_settings(conn, project_id),
    )
    return list(routing_config.lane_allowed_paths.get(lane, []))


def _max_chain_steps() -> int:
    from yoke_core.api.routing_config import get_max_chain_steps
    from yoke_core.api.service_client_shared import _get_config_path

    return get_max_chain_steps(_get_config_path())


def handle_identity(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the calling session's stored identity plus its lane policy."""
    sid = _session_id(request)
    if not sid:
        return _err("session_required", "session id is required")

    from yoke_core.domain.sessions import SessionError
    from yoke_core.domain.sessions_ended_recovery import session_ended_message
    from yoke_core.domain.sessions_identity_read import resolve_session_identity

    with _connect_rw() as conn:
        try:
            identity = resolve_session_identity(conn, sid)
        except SessionError as exc:
            return _err(exc.code.lower(), exc.message)
        if identity.ended_at is not None:
            return _err("session_ended", session_ended_message(conn, sid))

        payload: Dict[str, Any] = {
            "session_id": identity.session_id,
            "executor": identity.executor,
            "executor_display_name": identity.executor_display_name,
            "provider": identity.provider,
            "model": identity.model,
            "execution_lane": identity.execution_lane,
            "lane_allowed_paths": _lane_allowed_paths(
                conn, identity.project_id, identity.execution_lane,
            ),
            "workspace": identity.workspace,
            "project_id": identity.project_id,
            "project_slug": _project_slug(conn, identity.project_id),
            "actor_id": identity.actor_id,
            "actor_label": _actor_label(conn, identity.actor_id),
            "mode": identity.mode,
            "max_chain_steps": _max_chain_steps(),
        }
    return HandlerOutcome(result_payload=payload)


__all__ = ["IdentityRequest", "IdentityResponse", "handle_identity"]
