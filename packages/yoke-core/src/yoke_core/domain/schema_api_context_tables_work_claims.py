"""Claims-topic schema packet entry for typed session work claims."""

from __future__ import annotations


WORK_CLAIM_TABLES: dict[str, dict] = {
    "work_claims": {
        "columns": [
            ("id", "INTEGER"),
            ("session_id", "TEXT"),
            ("target_kind", "TEXT"),
            ("item_id", "INTEGER"),
            ("epic_id", "INTEGER"),
            ("task_num", "INTEGER"),
            ("process_key", "TEXT"),
            ("conflict_group", "TEXT"),
            ("steering_project_id", "INTEGER"),
            ("steering_strategy_doc_slugs", "TEXT"),
            ("owner_kind", "TEXT"),
            ("owner_item_id", "INTEGER"),
            ("owner_session_id", "TEXT"),
            ("owner_work_claim_id", "INTEGER"),
            ("registered_by_actor_id", "INTEGER"),
            ("registered_by_session_id", "TEXT"),
            ("claim_type", "TEXT"),
            ("claimed_at", "TEXT"),
            ("last_heartbeat", "TEXT"),
            ("released_at", "TEXT"),
            ("release_reason", "TEXT"),
            ("reason", "TEXT"),
            ("reason_intent", "TEXT"),
            ("release_reason_intent", "TEXT"),
        ],
        "notes": (
            "Typed targets use target_kind plus the matching specialized "
            "columns: item_id (kind=item), (epic_id, task_num) "
            "(kind=epic_task), (process_key, conflict_group) "
            "(kind=process), or (steering_project_id, "
            "steering_strategy_doc_slugs) (kind=steering_scope). The "
            "steering slug column is canonical JSON: [] means the whole "
            "project; otherwise it is the closed strategy-document set. "
            "Intersecting live steering scopes in one project refuse with "
            "the steering claim holder named; ordinary release and stale-"
            "session reclaim free the scope. Typed ownership is authority: "
            "a steering-scope row has owner_kind='session' with "
            "owner_session_id populated. registered_by_actor_id and "
            "registered_by_session_id are registration provenance, not "
            "authority. There is no single generic target column and no "
            "target_path column; worktree/path coverage lives elsewhere. "
            "claim_type is 'exclusive'; non-terminal state is derived from "
            "released_at IS NULL, with no state/status column. Primary key "
            "is id; there is no claim_id column. The claim timestamp is "
            "claimed_at, not created_at. For holder lookups prefer `yoke "
            "claims work holder-get PREFIX-N`; for a path use `yoke claims "
            "work holder-get --path /abs/path`. Writing into another live "
            "session's lane is refused (failure_class=foreign_lane, event "
            "SessionCwdForeignLaneDenied); holding no claim is not "
            "permission. Two processes in one worktree share its git index. "
            "Canonical active-session query: `SELECT id, target_kind, "
            "item_id, epic_id, task_num, steering_project_id, claimed_at "
            "FROM work_claims WHERE session_id = ? AND released_at IS "
            "NULL`. Acquire/release intent is row state: reason is the "
            "verbatim acquire rationale, reason_intent its canonical "
            "classification, and release_reason_intent the caller's release "
            "intent versus the release_reason enum. Read these columns, "
            "never the telemetry-only events ledger; NULL means no intent "
            "was recorded."
        ),
    },
}


__all__ = ["WORK_CLAIM_TABLES"]
