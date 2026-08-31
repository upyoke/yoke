"""Actor table entries for the schema cheat sheet."""

from __future__ import annotations


ACTOR_TABLES: dict[str, dict] = {
    "actors": {
        "columns": [
            ("id", "INTEGER"),
            ("kind", "TEXT"),
            ("system_component", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Actor identity referenced by work_claims.actor_id, "
            "path_claims.registered_by_actor_id, and similar foreign keys. kind "
            "is 'human' or 'system'; system_component is the bound "
            "component name when kind is system-attributed. Human-readable "
            "names live in actor_labels as surface-specific projections: "
            "display for generic actor views, github_label for GitHub sync."
            " actors has NO org_id column; resolve an actor's organization "
            "membership through actor_org_roles.org_id."
        ),
    },
    "actor_labels": {
        "columns": [
            ("id", "INTEGER"),
            ("actor_id", "INTEGER"),
            ("surface", "TEXT"),
            ("label", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Surface-specific actor labels. surface='display' is the "
            "generic actor-facing display projection; surface='github_label' "
            "is the GitHub sync projection. One label per actor per surface "
            "on every surface. One actor per surface/label pair only on the "
            "resolution surfaces (github_label): display labels are names, "
            "so two actors may carry the same one. Write a display label "
            "with actor_display.set_actor_display_name, which upserts; "
            "actors.set_actor_label binds once and no-ops on a relabel."
        ),
    },
}


__all__ = ["ACTOR_TABLES"]
