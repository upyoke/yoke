"""Coordination-lease table metadata for the schema cheat sheet."""

from __future__ import annotations


LEASE_TABLES: dict[str, dict] = {
    "coordination_leases": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("lease_key", "TEXT"),
            ("session_id", "TEXT"),
            ("actor_id", "TEXT"),
            ("acquired_at", "TEXT"),
            ("heartbeat_at", "TEXT"),
            ("released_at", "TEXT"),
            ("release_reason", "TEXT"),
            ("owner_kind", "TEXT"),
            ("owner_item_id", "INTEGER"),
            ("owner_session_id", "TEXT"),
            ("owner_work_claim_id", "INTEGER"),
            ("released_by_session_id", "TEXT"),
            ("released_by_actor_id", "TEXT"),
        ],
        "notes": (
            "Shared-operation lease keyed on (project_id, lease_key). "
            "session_id is acquire-time registration, not the holder. "
            "The holder is owner_kind ∈ (item, session, process) plus "
            "the matching owner_item_id / owner_session_id / "
            "owner_work_claim_id. Rehearsal holds are item-owned; "
            "operator_release writes released_by_session_id / "
            "released_by_actor_id and never copies the prior holder. "
            "There is no leases.holder column."
        ),
    },
}


__all__ = ["LEASE_TABLES"]
