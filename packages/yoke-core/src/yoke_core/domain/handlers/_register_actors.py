"""Browser-facing, read-only Actors roster."""

from __future__ import annotations

from yoke_core.domain.handlers import actor_state, actors_roster


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
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["org_admin"],
        adapter_status="internal",
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
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["authenticated_actor"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
