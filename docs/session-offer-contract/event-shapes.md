# Event Shapes

Two events are emitted as part of the session-offer loop. Both conform to the envelope structure documented in `event-contract.md`. Cross-link back from [session-offer-contract.md](../session-offer-contract.md) for the request/response envelope, identity model, and adapter responsibilities that drive these emissions.

## HarnessSessionOffered

Emitted when a harness session offers itself to Yoke.

| Field | Value |
|-------|-------|
| `event_name` | `HarnessSessionOffered` |
| `event_kind` | `system` |
| `event_type` | `session_offer` |
| `severity` | `INFO` |
| `source_type` | `backend` |

**Minimum `envelope.context` fields:**

| Context Field | Source |
|---------------|--------|
| `session_id` | `SessionOffer.session_id` |
| `executor` | `SessionOffer.executor` |
| `provider` | `SessionOffer.provider` |
| `model` | `SessionOffer.model` |
| `execution_lane` | `SessionOffer.execution_lane` |
| `workspace` | `SessionOffer.workspace` |
| `capabilities` | `SessionOffer.capabilities` |
| `supported_paths` | `SessionOffer.supported_paths` |

**Emission point:** The canonical `HarnessSessionOffered` event is emitted in the shared `session_offer_with_ownership` path (in `sessions.py`), so both CLI and API adapters emit it consistently without duplication.

## NextActionChosen

Emitted when the core decides what directive to give a session.

| Field | Value |
|-------|-------|
| `event_name` | `NextActionChosen` |
| `event_kind` | `workflow` |
| `event_type` | `session_directive` |
| `severity` | `STATUS` |
| `source_type` | `backend` |

**Minimum `envelope.context` fields:**

| Context Field | Source |
|---------------|--------|
| `session_id` | `NextAction.correlation_id` |
| `action` | `NextAction.action` (string value) |
| `reason` | `NextAction.reason` |
| `correlation_id` | `NextAction.correlation_id` |
| `supported_paths` | Declared paths from the offer (when non-empty) |

When the action is `escalate` with `escalate_reason: "unsupported_path"`, the context also includes `required_path` (the path the item needs).

When the action is `wait` with `wait_reason: "no_lane_compatible_work"`, the context also includes `actual_lane`, `lane_filtered_count`, `lane_filtered_note`, `lane_filtered_items`, and a `lane_filtered_paths` grouping — see [action-payloads.md](action-payloads.md) for the payload shape. The event envelope mirrors these keys so telemetry consumers can distinguish the lane-filtered WAIT from the truly-empty WAIT and from `wait_reason: "lane_policy_disallows_path"` (a selected item or process action needs a path the actual lane does not allow) without parsing reason text. When the frontier also carries lane-filtered detail under blocker-driven escalations, the same lane keys ride along on the `escalate` event envelope.

**Emission point:** The canonical `NextActionChosen` event is emitted via `emit_next_action_chosen()` in `sessions.py`, called by both CLI and API adapters after `decide_next_action` returns.

## ChainStepCompleted

Emitted after a `/yoke do` mode handler returns, recording the handler outcome so that dropped chains are visible in telemetry.

| Field | Value |
|-------|-------|
| `event_name` | `ChainStepCompleted` |
| `event_kind` | `workflow` |
| `event_type` | `chain_checkpoint` |
| `severity` | `STATUS` |
| `source_type` | `backend` |

**Minimum `envelope.context` fields:**

| Context Field | Source |
|---------------|--------|
| `session_id` | The active session ID |
| `step` | Loop iteration number (1-based) |
| `action` | The action that was executed (`charge`, `resume`, etc.) |
| `chainable` | Whether the action declared itself chainable |
| `handler_outcome` | Handler exit disposition (`completed`, etc.) |
| `item_id` | Targeted work identifier (when applicable) |
| `task_num` | Epic task number (when applicable) |
| `status` | Persisted current status for no-progress resume detection (when available) |
| `required_path` | Canonical downstream path derived from scheduler truth (when available) |

**Emission point:** Emitted by `update_chain_checkpoint()` in `sessions.py`, called by the loop's Step B via `service_client.py session-checkpoint`.

**Persistence:** The checkpoint data is stored in the `chain_checkpoint` key within the session's `offer_envelope` JSON column on `harness_sessions`. Step C of the loop reads this persisted state via `session-checkpoint-read` rather than relying on prompt-local variables that may be lost after long handlers. The same envelope also persists `max_chain_steps` so normal session shutdown can reject premature cleanup with `CHAIN_PENDING`.

## SchedulerOfferSkipped

Emitted when `/yoke do` skips a stale lifecycle offer, a live-claim conflict, a disabled process offer, or a recoverable substrate failure before treating it as useful work.

Minimum context: `session_id`, `skip_reason`, `chain_step`, plus `item_id` or `process_key`. Item skips may include `recommended_action`, `current_status`, `claim_holder_session_id`, `claim_id`, `claimed_at`, and `holder_unknown`. Process skips include `config_key` and `recommended_action`.

## ChainBudgetUnused

Emitted when an offer becomes non-chainable while useful chain budget remains. Minimum context: `session_id`, `step`, `max_chain_steps`, `remaining_budget`, `terminal_reason`, and `candidate_trail`.

## ChainDeclineOverridden

Emitted when a caller intentionally bypasses the structural chain-end guard with the explicit override flag and a non-empty rationale. Minimum context: `session_id`, `checkpoint_step`, `max_chain_steps`, `rationale`, `action`, `item_id`, and `override_flag`.
