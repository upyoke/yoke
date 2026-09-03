"""Claims-topic schema packet entry for typed session work claims."""

from __future__ import annotations


WORK_CLAIM_TABLES: dict[str, dict] = {
    "work_claims": {
        "columns": [
            ("id", "INTEGER"),
            ("session_id", "TEXT"),
            ("target_kind", "TEXT"),
            ("scope", "TEXT"),
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
            "Every typed target uses target_kind plus one canonical JSON "
            'object in scope: item={"item_id":N}, epic_task={"epic_id":N,'
            '"task_num":N}, process={"process_key":K,"conflict_group":G}, '
            'steering={"project_id":N}, migration_serialization='
            '{"project_id":N,"model":M,"item_id":N}, qa_admission='
            '{"machine_id":ID}, or route_qualification={"project_id":N,'
            '"grant_key":K}. Domain validation requires '
            "exactly the keys for the named kind. Steering has one live "
            "session-owned seat per project; strategy-document locks remain "
            "in strategy_doc_claims. The last three kinds are the "
            "shared-operation claims that replaced the retired "
            "lease table it replaced: migration territory per model, one "
            "physical test machine, one private-route qualification grant. "
            "They are STICKY — the stale-session sweep and session-end "
            "release skip them, because the resource keeps running after "
            "the session goes quiet, so recovery is the human-only `yoke "
            "coordination-claim release --project P --key K --reason R`. "
            "Their exclusivity unit is the whole scope except "
            "migration_serialization, which conflicts on (project_id, "
            "model) so item_id records the owner rather than the resource. "
            "Read and address them by their operator key "
            "(LIVE_DB_MIGRATION:<model>, QA_HOST:<machine>) via `yoke "
            "coordination-claim list [--active-only]`. There is no "
            "specialized target column or "
            "target_path column; worktree/path coverage lives elsewhere. "
            "claim_type is 'exclusive'; non-terminal state is derived from "
            "released_at IS NULL, with no state/status column. Primary key "
            "is id; there is no claim_id column. The claim timestamp is "
            "`claimed_at`, not `created_at`. For holder lookups prefer `yoke "
            "claims work holder-get PREFIX-N`; for a path use `yoke claims "
            "work holder-get --path /abs/path`. Writing into another live "
            "session's lane is refused (failure_class=foreign_lane, event "
            "SessionCwdForeignLaneDenied); holding no claim is not "
            "permission. Two processes in one worktree share its git index. "
            "Surveying a neighbour lane read-only IS allowed: one plain "
            "`git -C <lane> status|diff|log|show|ls-files|rev-parse|blame` "
            "call, no redirection, chaining, or --output file. "
            "Canonical active-session query: `SELECT id, target_kind, "
            "scope, claimed_at "
            "FROM work_claims WHERE session_id = ? AND released_at IS "
            "NULL`. Acquire/release intent is row state: reason is the "
            "verbatim acquire rationale, reason_intent its canonical "
            "classification, and release_reason_intent the caller's release "
            "intent versus the release_reason enum. Read these columns, "
            "never the telemetry-only events ledger; NULL means no intent "
            "was recorded. A session serializing behind another item must "
            "not treat the peer's status as the landing signal — status is "
            "what strands after a cap-overruled close-out. The durable "
            "landed facts are the merge receipt, items.merged_at / "
            "merge_queue_landed_at, and git ancestry of the merge sha."
        ),
    },
}


__all__ = ["WORK_CLAIM_TABLES"]
