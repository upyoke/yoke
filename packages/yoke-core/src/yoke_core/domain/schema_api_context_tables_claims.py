"""``claims`` topic table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds the ``claims``
topic entries: harness_sessions, work_claims, path_claims,
path_claim_targets, path_claim_overrides, path_targets,
path_claim_amendments, actors, actor_labels.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations

from yoke_core.domain.schema_api_context_tables_actors import ACTOR_TABLES


CLAIMS_TABLES: dict[str, dict] = {
    "harness_sessions": {
        "columns": [
            ("session_id", "TEXT"),
            ("executor", "TEXT"),
            ("executor_display_name", "TEXT"),
            ("provider", "TEXT"),
            ("model", "TEXT"),
            ("mode", "TEXT"),
            ("execution_lane", "TEXT"),
            ("offer_envelope", "TEXT"),
            ("current_item_id", "TEXT"),
            ("current_item_set_at", "TEXT"),
            ("recent_item_id", "TEXT"),
            ("recent_item_status", "TEXT"),
            ("recent_item_recorded_at", "TEXT"),
            ("actor_id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("offered_at", "TEXT"),
            ("last_heartbeat", "TEXT"),
            ("ended_at", "TEXT"),
            ("last_tool_call_at", "TEXT"),
            ("tool_call_count", "INTEGER"),
            ("episode_started_at", "TEXT"),
            ("pending_resume_notice", "TEXT"),
            ("last_chain_step", "INTEGER"),
            ("last_checkpoint_at", "TEXT"),
        ],
        "notes": (
            "executor stores only the canonical harness_id enum values "
            "claude-code or codex (resolved at write time via "
            "runtime.harness.hook_helpers_identity.canonical_harness_id); "
            "the surface-specific alias (claude-desktop, codex-vscode, "
            "claude-vscode, codex-cli, codex-desktop, etc.) lives in "
            "executor_display_name when known and is NULL otherwise. "
            "Board/session rendering prefers executor_display_name and "
            "falls back to executor; event-envelope executor fields are "
            "canonical-only. The primary key is `session_id` — there is "
            "NO `id` column on this table (stale guess). Primary "
            "attribution key is current_item_id "
            "(set when the session is actively working on an item); "
            "recent_item_id / recent_item_status / recent_item_recorded_at "
            "carry the most recent item the session worked after "
            "current_item_id clears. mode is the session's queue posture "
            "('wait' / 'busy' / etc); offer_envelope is the JSON "
            "session-offer payload (see JSON-nested-field schemas below). "
            "The authoritative routing lane is execution_lane on this row; "
            "session-offer anchors on it and treats caller-supplied "
            "--lane / request body execution_lane values as advisory only "
            "(mismatches emit SessionOfferLaneOverrideIgnored). Legacy "
            "session-attribution column names predate the typed "
            "work-claim model and are NOT on this table. There is NO "
            "`status` column on harness_sessions; use mode for queue "
            "posture and recent_item_status for the most recent item "
            "lifecycle snapshot. There is NO `active` column; use "
            "ended_at / last_heartbeat plus work_claims for liveness and "
            "ownership. There is likewise NO `state` column — the posture "
            "column is `mode` and the recent-item lifecycle snapshot is "
            "`recent_item_status`, neither named `state` — and NO "
            "`started_at` column: the session-offer timestamp is "
            "`offered_at`, with liveness / teardown on last_heartbeat / "
            "ended_at. Tool-call liveness is first-class state: "
            "last_tool_call_at / tool_call_count are stamped by the "
            "observe pipeline on each HarnessToolCallCompleted/Failed — "
            "read these columns, never MAX(events.created_at) (the "
            "events ledger is telemetry-only). episode_started_at is "
            "the current-episode boundary (stamped at register and "
            "reactivation; who-claims --current-episode resolves from "
            "it). pending_resume_notice is the render-once slim "
            "resume-block payload (written at reactivation, cleared at "
            "render). Chain progress is likewise first-class state: "
            "last_chain_step / last_checkpoint_at are stamped by "
            "update_chain_checkpoint on every ChainStepCompleted and "
            "survive offer-envelope rewrites — read them instead of "
            "MAX(step) over ChainStepCompleted envelopes (that state "
            "previously lived only in event envelopes; the events ledger "
            "is telemetry-only). project_id is the session's client-resolved "
            "project identity, stamped from the installing machine's checkout "
            "mapping at registration. workspace is display/debug context "
            "only; never join or prefix-match workspace against a shared "
            "project row to infer project identity."
        ),
    },
    "session_tool_calls": {
        "columns": [
            ("id", "INTEGER"),
            ("session_id", "TEXT"),
            ("tool_use_id", "TEXT"),
            ("tool_name", "TEXT"),
            ("started_at", "TEXT"),
            ("completed_at", "TEXT"),
            ("outcome", "TEXT"),
            ("command_summary", "TEXT"),
        ],
        "notes": (
            "Rolling per-tool-call state (short retention, ~7d via the "
            "events prune). The observe pipeline opens a row on "
            "HarnessToolCallStarted and closes it (completed_at + "
            "outcome) on the completion event; open rows "
            "(completed_at IS NULL) are the orphan set the session-end "
            "sweep closes with outcome='interrupted'. command_summary "
            "is the bounded (500-char) command text the pre-tool-call "
            "lint guardrails scan. Unique key (session_id, "
            "tool_use_id). This table is state, not telemetry — the "
            "matching HarnessToolCall* events remain in the events "
            "ledger for audit queries."
        ),
    },
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
            "Typed targets via target_kind plus the matching specialized "
            "columns: item_id (kind=item), (epic_id, task_num) "
            "(kind=epic_task), (process_key, conflict_group) "
            "(kind=process). There is no single generic target column on "
            "this table — pick the matching kind-specific columns above. "
            "There is also NO `target_path` column (stale guess); worktree "
            "and path coverage live outside work_claims. "
            "claim_type is the kind discriminator (e.g. 'exclusive'); "
            "non-terminal state is derived from `released_at IS NULL` — "
            "the table has no separate state/status column. Primary key "
            "is `id`; there is NO `claim_id` column. "
            "Disambiguation from path_claims: owner_kind / owner_item_id / "
            "owner_session_id / registered_by_actor_id / "
            "registered_by_session_id are path_claims columns, NOT "
            "work_claims — do not cross-apply the typed-owner vocabulary "
            "here; a work_claims row's authority is just session_id + "
            "target_kind + item_id/epic_id/task_num. The claim timestamp "
            "is `claimed_at` (there is no `created_at` on this table). For "
            "holder lookups prefer `yoke claims work holder-get YOK-N` "
            "over a raw SELECT against this table. "
            "Canonical SELECTs: all active claims a session holds — "
            "`SELECT id, item_id, epic_id, task_num, claim_type, "
            "claimed_at FROM work_claims WHERE session_id = ? AND "
            "released_at IS NULL`; all sessions currently claiming a "
            "given item — `SELECT session_id, claim_type, claimed_at "
            "FROM work_claims WHERE item_id = ? AND released_at IS NULL`. "
            "Acquire/release intent is first-class state on the row: "
            "`reason` is the verbatim --reason supplied at acquire, "
            "`reason_intent` its canonical-vocabulary classification "
            "(NULL = free text), and `release_reason_intent` the "
            "caller-supplied intent at release (vs the schema-enum "
            "release_reason). These previously lived only in "
            "WorkClaimed/WorkReleased event envelopes — read the columns, "
            "never the events ledger (telemetry-only); NULL means no "
            "intent was recorded."
        ),
    },
    "path_claims": {
        "columns": [
            ("id", "INTEGER"),
            ("state", "TEXT"),
            ("mode", "TEXT"),
            ("actor_id", "INTEGER"),
            ("session_id", "TEXT"),
            ("item_id", "INTEGER"),
            ("work_claim_id", "INTEGER"),
            ("owner_kind", "TEXT"),
            ("owner_item_id", "INTEGER"),
            ("owner_session_id", "TEXT"),
            ("owner_work_claim_id", "INTEGER"),
            ("registered_by_actor_id", "INTEGER"),
            ("registered_by_session_id", "TEXT"),
            ("integration_target", "TEXT"),
            ("base_commit_sha", "TEXT"),
            ("registered_at", "TEXT"),
            ("activated_at", "TEXT"),
            ("released_at", "TEXT"),
            ("cancelled_at", "TEXT"),
            ("release_reason", "TEXT"),
            ("cancel_reason", "TEXT"),
            ("blocked_reason", "TEXT"),
            ("exception_reason", "TEXT"),
        ],
        "notes": (
            "State enum: 'planned' | 'active' | 'released' | 'cancelled' "
            "| 'blocked'. Typed ownership is explicit: owner_kind ∈ "
            "('item','session','process') and the matching one of "
            "owner_item_id / owner_session_id / owner_work_claim_id is "
            "populated. New readers MUST consult typed owner fields — "
            "NEVER treat the legacy session_id column as path authority; "
            "it is provenance ONLY (the registering session, same as "
            "registered_by_session_id). An item-owned claim survives the "
            "registering session ending. The legacy actor_id / session_id "
            "/ item_id / work_claim_id columns remain populated alongside "
            "the typed owner fields during cutover for backwards "
            "compatibility and roundtrip; readers should prefer the "
            "typed columns. HC-path-claim-owner-kind flags non-terminal "
            "rows that lack typed ownership or carry contradictory "
            "owner_kind / owner-field combinations. Lookup by item via "
            "`yoke claims path list --item YOK-N`. Covered-path list "
            "is an API response field, not a column — there is no "
            "`path_claims.paths`, `path_claims.path`, or bare `path` "
            "column (stale guesses). It is reachable only by JOIN through "
            "path_claim_targets -> "
            "path_targets.path_string. "
            "Canonical JOIN: `SELECT ptarget.path_string FROM path_claims "
            "pc JOIN path_claim_targets pct ON pct.claim_id = pc.id JOIN "
            "path_targets ptarget ON ptarget.id = pct.target_id WHERE "
            "pc.owner_kind = 'item' AND pc.owner_item_id = ? AND "
            "pc.state = 'active'`. Activation records the "
            "integration-target head SHA on `base_commit_sha` (TEXT). "
            "Non-terminal predicate is `state IN ('planned', 'blocked', "
            "'active')`; terminal is `state IN ('released', "
            "'cancelled')`. Do NOT use `released_at IS NULL` to filter "
            "path_claims for non-terminal rows — cancelled rows carry "
            "`released_at = NULL` with only `cancelled_at` set, so the "
            "`released_at IS NULL` predicate would include them. Use the "
            "`state` predicate above. Canonical SELECTs: all "
            "non-terminal item-owned claims on an item — `SELECT id, "
            "integration_target, state, mode, registered_at FROM "
            "path_claims WHERE owner_kind='item' AND owner_item_id = ? "
            "AND state IN ('planned', 'blocked', 'active')`; all "
            "currently-active path claims on an integration target — "
            "`SELECT id, owner_kind, owner_item_id, owner_session_id, "
            "owner_work_claim_id, mode, activated_at FROM path_claims "
            "WHERE integration_target = ? AND state = 'active'`."
        ),
    },
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
    "path_claim_overrides": {
        "columns": [
            ("id", "INTEGER"),
            ("path_claim_id", "INTEGER"),
            ("blocking_claim_id", "INTEGER"),
            ("blocking_path_targets", "TEXT"),
            ("override_point", "TEXT"),
            ("conflict_reason", "TEXT"),
            ("integration_target", "TEXT"),
            ("actor_id", "INTEGER"),
            ("actor_reason", "TEXT"),
            ("item_id", "INTEGER"),
            ("project", "TEXT"),
            ("session_id", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Operator-collision approvals (state, not telemetry): one "
            "row permits path_claim_id to proceed past blocking_claim_id "
            "for the anchor targets in blocking_path_targets (JSON int "
            "array). Written by invoke_override "
            "(yoke_core.domain.path_claims_override) in the same "
            "transaction as the PathClaimOverride telemetry event; the "
            "overlap classifier's is_active_override gates on these "
            "rows — never on the events ledger. Overrides auto-retire "
            "via the participating path_claims rows (terminal state or "
            "anchors narrowed out of the blocker's coverage), so rows "
            "here are never deleted on retirement. override_point ∈ "
            "('creation','amend','revalidation_conflict')."
        ),
    },
    "path_targets": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("kind", "TEXT"),
            ("path_string", "TEXT"),
            ("generation", "INTEGER"),
            ("parent_target_id", "INTEGER"),
            ("created_at", "TEXT"),
            ("materialization_state", "TEXT"),
            ("materialization_updated_at", "TEXT"),
            ("planned_by_item_id", "INTEGER"),
            ("planned_by_claim_id", "INTEGER"),
        ],
        "notes": (
            "Path-snapshot rows. path_string is the canonical relative "
            "path (e.g. 'runtime/api/domain/foo.py'). kind is 'file' or "
            "'directory'. materialization_state is 'observed' (exists on "
            "integration target) or 'planned' (claim-minted future file "
            "via --allow-planned). There is NO `path` column; use "
            "`path_string`."
        ),
    },
    "path_claim_amendments": {
        "columns": [
            ("id", "INTEGER"),
            ("claim_id", "INTEGER"),
            ("amended_at", "TEXT"),
            ("amendment_kind", "TEXT"),
            ("payload", "TEXT"),
            ("reason", "TEXT"),
        ],
        "notes": (
            "Append-only history of widen / narrow / cancel-amendment "
            "operations on a path_claims row. amendment_kind names the "
            "operation; payload is JSON (e.g. {'added': [target_id, ...]}); "
            "reason is the operator-authored rationale."
        ),
    },
    **ACTOR_TABLES,
}
