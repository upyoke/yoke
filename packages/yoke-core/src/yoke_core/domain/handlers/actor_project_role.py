"""Org-admin operations that set or remove a person's role on one project."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.actor_project_role import (
    ProjectRoleChange,
    remove_actor_project_role,
    set_actor_project_role,
)
from yoke_core.domain.handlers.actor_role import run_person_change, text_field


class ActorProjectRoleSetRequest(BaseModel):
    actor_id: Optional[int] = None
    member_email: Optional[str] = None
    project: str
    role: str


class ActorProjectRoleSetResponse(BaseModel):
    actor_id: int
    project: str
    role: str
    previous_roles: List[str]
    changed: bool


class ActorProjectRoleRemoveRequest(BaseModel):
    actor_id: Optional[int] = None
    member_email: Optional[str] = None
    project: str


class ActorProjectRoleRemoveResponse(BaseModel):
    actor_id: int
    project: str
    previous_roles: List[str]
    changed: bool


def _payload(done: ProjectRoleChange) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "actor_id": done.actor_id,
        "project": done.project,
        "previous_roles": done.previous_roles,
        "changed": done.changed,
    }
    if done.role is not None:
        result["role"] = done.role
    return result


def handle_actor_project_role_set(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    project = text_field(payload, "project", "a project slug or id")
    if isinstance(project, HandlerOutcome):
        return project
    role = text_field(payload, "role", "a role name")
    if isinstance(role, HandlerOutcome):
        return role
    return run_person_change(
        request,
        lambda conn, actor_id, caller: _payload(
            set_actor_project_role(
                conn,
                actor_id=actor_id,
                project=project,
                role=role,
                caller_actor_id=caller,
            )
        ),
    )


def handle_actor_project_role_remove(request: FunctionCallRequest) -> HandlerOutcome:
    project = text_field(request.payload or {}, "project", "a project slug or id")
    if isinstance(project, HandlerOutcome):
        return project
    return run_person_change(
        request,
        lambda conn, actor_id, caller: _payload(
            remove_actor_project_role(
                conn, actor_id=actor_id, project=project, caller_actor_id=caller
            )
        ),
    )
