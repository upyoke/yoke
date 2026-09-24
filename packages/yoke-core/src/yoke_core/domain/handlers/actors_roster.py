"""Read-only roster for the Actors workbench page."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.profile_read import read_identity, read_roles


class ActorsRosterRequest(BaseModel):
    pass


class ActorsRosterResponse(BaseModel):
    rows: List[Dict[str, Any]]
    current_actor_id: Optional[int]


def handle_actors_roster(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="actors.roster requires target.kind='global'; retry without a project target",
                jsonpath="$.target.kind",
            ),
        )

    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        actors = conn.execute(
            "SELECT id, kind, name, system_component FROM actors ORDER BY id"
        ).fetchall()
        rows = []
        for actor_id, kind, name, system_component in actors:
            actor_id = int(actor_id)
            rows.append(
                {
                    "id": actor_id,
                    "kind": kind,
                    "name": name or system_component or f"actor {actor_id}",
                    "roles": read_roles(conn, actor_id),
                    "identity": read_identity(conn, actor_id),
                }
            )
    finally:
        conn.close()

    raw_actor_id = (request.actor.actor_id or "").strip()
    current_actor_id = int(raw_actor_id) if raw_actor_id.isdigit() else None
    return HandlerOutcome(
        result_payload={"rows": rows, "current_actor_id": current_actor_id},
        primary_success=True,
    )
