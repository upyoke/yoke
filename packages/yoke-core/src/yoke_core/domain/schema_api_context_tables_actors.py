"""Actor table entries for the schema cheat sheet."""

from __future__ import annotations


ACTOR_TABLES: dict[str, dict] = {
    "actors": {
        "columns": [
            ("id", "INTEGER"),
            ("kind", "TEXT"),
            ("system_component", "TEXT"),
            ("name", "TEXT"),
            ("status", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Actor identity referenced by work_claims.actor_id, "
            "path_claims.registered_by_actor_id, and similar foreign keys. kind "
            "is 'human' or 'system'; system_component is the bound "
            "component name when kind is system-attributed. name is the ONE "
            "human-readable name every surface renders (read it with "
            "actors.actor_name, write it with actors.set_actor_name) and it "
            "carries no uniqueness: two people may share a name, and nothing "
            "resolves an identity from it. There is no per-surface name "
            "projection and no actor_labels table (wrong guesses: "
            "actor_labels, surface='display', surface='github_label', "
            "actor_display.actor_display_name, actors.actor_label, "
            "actors.set_actor_label, actors.resolve_actor_by_label). "
            "actors.resolve_actors_by_name is an operator SEARCH returning a "
            "list; never use it to pick a session identity, an authenticated "
            "caller, or an owner. actors has NO org_id column; resolve an "
            "actor's organization membership through actor_org_roles.org_id. "
            "status is active or disabled; disabled actors have no authority "
            "even when their historical role grants remain. Org admins use "
            "actors.state.set to change status. Retiring a system actor "
            "requires an audit of its live dependencies and explicit "
            "confirmation; the canonical core actor and actors with active "
            "deployment credentials cannot be disabled. Before the serving "
            "build boot-converges the additive status column, a paired "
            "db-admin client still drives the self-deploy on the old schema. "
            "Authorization uses actor_state.actor_is_active or "
            "actor_state.actor_active_sql, not a direct SELECT of "
            "actors.status (the wrong pre-converge guess). A legacy actor "
            "row is active; once status exists, only active is authorized."
        ),
    },
}


__all__ = ["ACTOR_TABLES"]
