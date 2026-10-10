"""Claims-topic schema packet entry for typed session work claims."""

from __future__ import annotations


WORK_CLAIM_TABLES: dict[str, dict] = {
    "strategy_doc_claims": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("strategy_doc_slug", "TEXT"),
            ("owner_kind", "TEXT"),
            ("owner_item_id", "INTEGER"),
            ("owner_session_id", "TEXT"),
            ("steering_claim_id", "INTEGER"),
            ("registered_at", "TEXT"),
            ("released_at", "TEXT"),
            ("release_reason", "TEXT"),
        ],
        "notes": (
            "A session document lock paired to steering stores the exact "
            "work_claims.id in steering_claim_id; releasing a seat must "
            "release only that lock. The earlier assumption that every "
            "minimal SQLite fixture supplies strategy_doc_claims.id was "
            "wrong; schema-light reads check for the column first."
        ),
    },
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
            'steering={"project_id":N} or {"project_id":N,'
            '"document":SLUG}, migration_serialization='
            '{"project_id":N,"model":M,"item_id":N}, qa_admission='
            '{"machine_id":ID}, or route_qualification={"project_id":N,'
            '"grant_key":K}. Released deploy_serialization rows are '
            "retained history of a retired kind nothing takes any more. "
            "Domain validation requires "
            "exactly the required keys for the named kind; steering also "
            "accepts the optional document key. A steering seat covers a "
            "whole project or one strategy document identified by owning "
            "project plus slug. Project steering covers unlinked items and "
            "CURRENT-PLAN members in that project; any other linked item is "
            "excluded even with no document seat. Document steering covers "
            "every item linked to that exact document across projects. A "
            "project seat overlaps CURRENT-PLAN document steering of the "
            "same project; two different documents do not overlap. "
            "Strategy-document locks remain in strategy_doc_claims. "
            "Migration serialization and QA admission are STICKY — the stale-session sweep and session-end "
            "release skip them, because the resource keeps running after "
            "the session goes quiet. Route qualification is not sticky. "
            "The holder of a live QA_HOST claim "
            "releases it with `yoke claims coordination-claim release "
            "--claim-id N --reason TEXT`; permission resolves from the "
            "holding session's project because the scope names only the "
            "machine. After reviewing a stranded row, recovery uses the "
            "signed-in human registered action outside any harness "
            "session: `yoke coordination-"
            "claim release [--project P] --key K --claim-id N --holder-session-"
            "id S --reason R`; it works over HTTPS or local authority and "
            "refuses a changed claim or holder. A release actor is recorded in "
            "event context, not a released_by_actor_id column on work_claims; "
            "the durable audited reason is release_reason_intent. Full claim "
            "list enrichment reads harness_sessions.actor_id; a minimal fixture "
            "without that column cannot execute the enriched list. Authorization "
            "instead reads claim id/scope and the holder project only. "
            "QA_HOST keys are machine-scoped: "
            "omit --project for operator release and list by --key; the list "
            "ignores project filters. Other kinds require --project for recovery. "
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
