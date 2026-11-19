"""Actor roster, state-change, org-role and project-role function registrations."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    actor_project_role,
    actor_role,
    actor_state,
    actors_roster,
)


def register(registry) -> None:
    registry.register(
        "actors.state.set",
        actor_state.handle_actor_state_set,
        actor_state.ActorStateSetRequest,
        actor_state.ActorStateSetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.actor_state",
        target_kinds=["global"],
        side_effects=["actors_update", "api_tokens_update", "api_token_audit_insert"],
        guardrails=["org_admin"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
    registry.register(
        "actors.role.set",
        actor_role.handle_actor_role_set,
        actor_role.ActorRoleSetRequest,
        actor_role.ActorRoleSetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.actor_role",
        target_kinds=["global"],
        side_effects=["actor_org_roles_delete", "actor_org_roles_insert"],
        guardrails=["org_admin"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
    registry.register(
        "actors.role.remove",
        actor_role.handle_actor_role_remove,
        actor_role.ActorRoleRemoveRequest,
        actor_role.ActorRoleRemoveResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.actor_role",
        target_kinds=["global"],
        side_effects=["actor_org_roles_delete"],
        guardrails=["org_admin"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
    registry.register(
        "actors.project_role.set",
        actor_project_role.handle_actor_project_role_set,
        actor_project_role.ActorProjectRoleSetRequest,
        actor_project_role.ActorProjectRoleSetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.actor_project_role",
        target_kinds=["global"],
        side_effects=["actor_project_roles_delete", "actor_project_roles_insert"],
        guardrails=["org_admin"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
    registry.register(
        "actors.project_role.remove",
        actor_project_role.handle_actor_project_role_remove,
        actor_project_role.ActorProjectRoleRemoveRequest,
        actor_project_role.ActorProjectRoleRemoveResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.actor_project_role",
        target_kinds=["global"],
        side_effects=["actor_project_roles_delete"],
        guardrails=["org_admin"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
    registry.register(
        "actors.roster",
        actors_roster.handle_actors_roster,
        actors_roster.ActorsRosterRequest,
        actors_roster.ActorsRosterResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.actors_roster",
        target_kinds=["global"],
        side_effects=[],
        guardrails=["authenticated_actor"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
