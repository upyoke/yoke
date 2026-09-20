"""``sessions.steering_groups.list`` — the live steering seats, and nothing else."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class SteeringGroupsListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SteeringGroupsListResponse(BaseModel):
    #: One row per live steering group, carrying the field the roster spells
    #: the same way, so a consumer ranking groups reads either source.
    rows: List[Dict[str, Any]] = Field(default_factory=list)


def handle_sessions_steering_groups_list(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="sessions.steering_groups.list requires target.kind='global'",
                jsonpath="$.target.kind",
            ),
        )
    payload = request.payload or {}
    if payload:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=(
                    "sessions.steering_groups.list takes no inputs: it answers "
                    "which steering groups are live for the calling actor; "
                    "remove "
                    + ", ".join(sorted(str(key) for key in payload))
                ),
                jsonpath="$.payload",
            ),
        )

    from yoke_core.domain import db_helpers
    from yoke_core.domain.actor_project_visibility import (
        actor_visible_project_ids,
        numeric_actor_id,
    )
    from yoke_core.domain.sessions_steering_groups_read import (
        live_steering_group_session_ids,
    )

    conn = db_helpers.connect()
    try:
        actor = request.actor.actor_id if request.actor else None
        session_ids = live_steering_group_session_ids(
            conn,
            visible_project_ids=actor_visible_project_ids(
                conn, numeric_actor_id(actor)
            ),
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "rows": [
                {"steering_group_session_id": session_id}
                for session_id in session_ids
            ]
        },
        primary_success=True,
    )


__all__ = [
    "SteeringGroupsListRequest",
    "SteeringGroupsListResponse",
    "handle_sessions_steering_groups_list",
]
