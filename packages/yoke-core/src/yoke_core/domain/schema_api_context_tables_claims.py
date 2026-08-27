"""``claims`` topic table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds the ``claims``
topic entries: harness_sessions, work_claims, path_claims,
path_claim_targets, path_claim_task_bindings, path_claim_overrides, path_targets,
path_claim_amendments, actors, actor_labels.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations

from yoke_core.domain.schema_api_context_tables_actors import ACTOR_TABLES
from yoke_core.domain.schema_api_context_tables_path_claim_bindings import (
    PATH_CLAIM_BINDING_TABLES,
)
from yoke_core.domain.schema_api_context_tables_work_claims import (
    WORK_CLAIM_TABLES,
)


CLAIMS_TABLES: dict[str, dict] = {
    "harness_sessions": {
        "columns": [
            ("session_id", "TEXT"),
            ("executor", "TEXT"),
            ("executor_surface", "TEXT"),
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
            ("turn_posture", "TEXT"),
            ("turn_posture_at", "TEXT"),
            ("ended_at", "TEXT"),
            ("terminated_at", "TEXT"),
            ("terminated_by_actor_id", "INTEGER"),
            ("terminated_by_session_id", "TEXT"),
            ("termination_reason", "TEXT"),
            ("last_tool_call_at", "TEXT"),
            ("tool_call_count", "INTEGER"),
            ("episode_started_at", "TEXT"),
            ("pending_resume_notice", "TEXT"),
            ("last_chain_step", "INTEGER"),
            ("last_checkpoint_at", "TEXT"),
        ],
        "notes": (
            "executor stores only the canonical harness_id enum values "
            "claude-code, codex, or cursor (resolved at write time via "
            "yoke_harness.hooks.identity.canonical_harness_id); "
            "the surface-specific alias (claude-desktop, codex-vscode, "
            "claude-vscode, codex-cli, codex-desktop, cursor-desktop, "
            "cursor-cli, etc.) lives in "
            "executor_surface when known and is NULL otherwise. "
            "Board/session rendering prefers executor_surface and "
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
            "The default routing lane is execution_lane on this row; "
            "session-offer uses it unless the caller supplies --lane / "
            "request body execution_lane, which overrides the row and "
            "emits SessionOfferLaneOverrideApplied. That override is for a "
            "DELIBERATE operator re-route only: an agent never resolves a "
            "lane of its own, because a lane guessed locally outranks the "
            "project's session-routing mapping and filters every frontier "
            "item behind a lane no lane_paths entry declares. Read the row "
            "back with `yoke sessions identity`, which returns this row's "
            "resolved identity plus the lane's permitted paths, and pass "
            "none of it onward. Legacy "
            "session-attribution column names predate the typed "
            "work-claim model and are NOT on this table. There is NO "
            "`status` column on harness_sessions; use mode for queue "
            "posture and recent_item_status for the most recent item "
            "lifecycle snapshot. There is NO `active` column; use "
            "ended_at / terminated_at / last_heartbeat plus work_claims for liveness and "
            "ownership. There is likewise NO `state` column — the posture "
            "column is `mode` and the recent-item lifecycle snapshot is "
            "`recent_item_status`, neither named `state` — and NO "
            "`started_at` column: the session-offer timestamp is "
            "`offered_at`, with liveness / teardown on last_heartbeat / "
            "ended_at. terminated_at is the permanent do-not-reactivate / "
            "do-not-wake terminal state; its actor, session, and reason "
            "columns record the authority that set it. Native turn posture is first-class state: "
            "turn_posture is running|waiting|unknown and turn_posture_at "
            "orders accepted hook/activity observations independently of "
            "claims, chain progress, and ended_at. Tool-call liveness is "
            "first-class state: "
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
            "project row to infer project identity. The sessions.begin "
            "entrypoint input helps canonicalize executor identity during "
            "registration; it is not stored in an `entrypoint` column, and "
            "harness_sessions has no such column."
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
    **WORK_CLAIM_TABLES,
    "path_claims": {
        "columns": [
            ("id", "INTEGER"),
            ("state", "TEXT"),
            ("mode", "TEXT"),
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
            "populated. An item-owned claim survives the registering "
            "session ending. HC-path-claim-owner-kind flags non-terminal "
            "rows that lack typed ownership or carry contradictory "
            "owner_kind / owner-field combinations. Lookup by item via "
            "`yoke claims path list --item PREFIX-N`. Covered-path list "
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
    **PATH_CLAIM_BINDING_TABLES,
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
            "path (e.g. '<project-source-path>/foo.py'). kind is 'file' or "
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
