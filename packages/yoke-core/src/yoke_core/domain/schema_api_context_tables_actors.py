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
            "path_claims.actor_id, and similar foreign keys. kind "
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
            "is the GitHub sync projection. The table is constrained to one "
            "label per actor per surface and one actor per surface/label pair."
        ),
    },
}


__all__ = ["ACTOR_TABLES"]
