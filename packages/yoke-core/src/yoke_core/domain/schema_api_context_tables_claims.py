"""``claims`` topic table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds the ``claims``
topic entries: harness_sessions, work_claims, path_claims,
path_claim_targets, path_claim_task_bindings, path_claim_overrides, path_targets,
path_claim_amendments, actors, actor_labels.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations

from yoke_core.domain.schema_api_context_harness_session_notes import (
    HARNESS_SESSION_NOTES,
)
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
            ("presentation_surface", "TEXT"),
            ("presentation_state", "TEXT"),
            ("presentation_mode", "TEXT"),
            ("presentation_source", "TEXT"),
            ("presentation_observed_at", "TEXT"),
            ("provider", "TEXT"),
            ("model", "TEXT"),
            ("reasoning_effort", "TEXT"),
            ("context_window_tokens", "INTEGER"),
            ("requested_model", "TEXT"),
            ("requested_reasoning_effort", "TEXT"),
            ("requested_context_window_tokens", "INTEGER"),
            ("mode", "TEXT"),
            ("quiet_reason", "TEXT"),
            ("keepalive_until", "TEXT"),
            ("keepalive_reason", "TEXT"),
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
            ("native_process_gone_at", "TEXT"),
            ("native_process_gone_evidence", "TEXT"),
            ("pending_resume_notice", "TEXT"),
            ("last_chain_step", "INTEGER"),
            ("last_checkpoint_at", "TEXT"),
        ],
        "notes": HARNESS_SESSION_NOTES,
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
            "sweep closes with outcome='interrupted'. An open row is NOT "
            "proof a command is still running: a call a pre-tool-call "
            "guardrail refused leaves one (join events on "
            "(session_id, tool_use_id) for HarnessToolCallDenied), and a "
            "harness that never closes rows leaves residue the session "
            "kept working past (compare started_at against "
            "harness_sessions.last_tool_call_at via "
            "session_reclaim_progress.open_tool_call_is_live). Both "
            "guards are why the steering fleet report can call a quiet "
            "holder in-flight rather than idle. command_summary "
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
