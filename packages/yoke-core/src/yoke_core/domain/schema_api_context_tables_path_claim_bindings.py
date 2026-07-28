"""Path-claim binding table metadata for the schema cheat sheet."""

from __future__ import annotations


PATH_CLAIM_BINDING_TABLES: dict[str, dict] = {
    "path_claim_targets": {
        "columns": [
            ("id", "INTEGER"),
            ("claim_id", "INTEGER"),
            ("target_id", "INTEGER"),
            ("declared_at", "TEXT"),
        ],
        "notes": (
            "Join table: path_claims (claim_id) -> path_targets "
            "(target_id). The covered-path list for a path claim is "
            "this join (path_targets.path_string carries the file path). "
            "There is NO `path_claim_id` column and NO `path` column."
        ),
    },
    "path_claim_task_bindings": {
        "columns": [
            ("claim_id", "INTEGER"),
            ("epic_id", "INTEGER"),
            ("task_num", "INTEGER"),
            ("bound_at", "TEXT"),
        ],
        "notes": (
            "Durable task scope for item-owned path claims. A row binds "
            "path_claims.claim_id to the generated Epic task identified by "
            "(epic_id, task_num). The binding carries no session or work-claim "
            "column: registering-session provenance is not path authority, "
            "and task coverage survives a session handoff. Worker enforcement "
            "intersects bound claim targets with epic_task_files; a persisted "
            "item_worktrees.lane_role='integration' lane receives their union."
        ),
    },
}


__all__ = ["PATH_CLAIM_BINDING_TABLES"]
