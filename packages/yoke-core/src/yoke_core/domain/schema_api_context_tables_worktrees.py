"""Universal worktree table entry for the schema cheat sheet."""

from __future__ import annotations

ITEM_WORKTREE_TABLES: dict[str, dict] = {
    "item_worktrees": {
        "columns": [
            ("id", "INTEGER"),
            ("item_id", "INTEGER"),
            ("branch", "TEXT"),
            ("path", "TEXT"),
            ("lane_role", "TEXT"),
            ("state", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
            ("released_at", "TEXT"),
        ],
        "notes": (
            "Universal worktree-lane authority for every workflow. lane_role "
            "is implementation, worker, or integration; state is active or "
            "released. An active path cannot be owned twice, and each item "
            "may have at most one active implementation or integration lane. "
            "Lanes do not own sessions. Session authority is derived from "
            "active work_claims joined through the claimed item or task. "
            "Read an item's exact interpreted policy with `yoke workflows "
            "item get PREFIX-N`; do not infer lane shape from workflow ids."
        ),
    },
}

__all__ = ["ITEM_WORKTREE_TABLES"]
