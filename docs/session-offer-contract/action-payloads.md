# Action-Specific Context Payloads

The `NextAction.context` dict carries action-specific data. These are conventions, not enforced schemas — adapters should handle missing keys gracefully. Cross-link back from [session-offer-contract.md](../session-offer-contract.md) for the request envelope, response envelope, identity model, event shapes, and adapter responsibilities that surround these payloads.

## resume

```json
{
 "item_id": "YOK-N",
 "status": "reviewed-implementation",
 "required_path": "polish"
}
```

Epic-task resumes use this shape instead:

```json
{
 "epic_id": 100,
 "task_num": 3,
 "status": "implementing",
 "required_path": "conduct"
}
```

`required_path` is derived from the same scheduler routing truth that charge uses. When a claimed work unit's current `required_path` is not supported by the harness, the core returns non-chainable `escalate` with `escalate_reason: "unsupported_path"`. When the lane policy excludes the path, the core returns the same non-chainable lane-policy outcome used by charge.

Repeated same-session `resume` responses are also bounded: if the prior persisted checkpoint was a completed `resume` for the same work at the same status or `required_path`, the next offer returns non-chainable `escalate` with `escalate_reason: "resume_no_progress"` instead of burning another chain step.

## charge

```json
{
 "selected_item": "YOK-N",
 "runnable_items": ["YOK-N", "YOK-N", "YOK-N"],
 "scheduler": {
 "next_step": "refine",
 "adapter": "refine",
 "item_type": "issue",
 "status": "idea",
 "title": "Implement feature X",
 "rank": 0,
 "explanation": "Ranked #1: refine for issue in idea"
 }
}
```

The `scheduler.next_step` field tells the adapter which command to invoke:
- `refine` — issue or epic refinement step, run refinement pipeline
- `shepherd` — epic in refined-idea/planning, run shepherd pipeline
- `conduct` — epic in planned/implementing/reviewing-implementation, run conduct pipeline
- `advance` — issue in refined-idea/implementing/reviewing-implementation, run `/yoke advance` in the main session
- `polish` — item in reviewed-implementation/polishing-implementation, run polish pipeline
- `usher` — implemented/release, merge and deploy

For issue implementation steps, `scheduler.adapter` may still show the raw frontier category (`conduct`) for ranking diagnostics, but `scheduler.next_step` is the dispatch truth and will be `advance`.

Yoke core checks the configured allowlist for the offering session's actual lane (`lane_paths_*`). If the required downstream path is not allowed for that lane, the decision engine returns `WAIT`.

## Session Shutdown

Normal `session-end` is guarded by two checks: (1) the persisted chain checkpoint — if `chain_checkpoint.chainable=true` and `chain_checkpoint.step < max_chain_steps`, the shared end-session surface returns `CHAIN_PENDING` and leaves the session active; and (2) the active-claim guard — if the session holds any unreleased claims, `end_session()` returns `ACTIVE_CLAIM` and refuses to terminate. `--force` does not bypass `CHAIN_PENDING`; callers must pass the explicit chain-end override flag plus a non-empty rationale, which emits `ChainDeclineOverridden`. Claims are released through the claim lifecycle (completed, handed_off, finalize-exit, offer-override) or stale-session reclamation (`clean-stale-sessions`). For stranded claims, use the human-only `python3 -m yoke_core.api.service_client claim-release` CLI.

## Offer-Time Claim Reconciliation

`session_offer_with_ownership()` eagerly claims the scheduler's selected item before `decide_next_action()` runs. When the final action is not `charge` (drift review chose `strategize`, `feed`, etc.), the session-offer adapters release the claim with intent `offer-override` before `set_session_mode()` and `emit_next_action_chosen()`. This ensures no phantom claim outlives the non-charge decision.

**Legacy stranded claims:** Claims orphaned by sessions that chose a non-charge action before this fix can be identified and released with the query below. The `NULLIF(envelope, '')::jsonb #>> '{context,action}'` fragment is the Postgres JSON-field accessor. Production code assembles it through `yoke_core.domain.sql_json.json_get`, which keeps the dialect in one file; this ad hoc operator query spells it out inline.

```bash
# Audit: find unreleased claims where the same session emitted a non-charge NextActionChosen.
yoke db read "
 SELECT wc.id, wc.session_id, wc.item_id, wc.claimed_at,
 e.created_at AS decision_at,
 NULLIF(e.envelope, '')::jsonb #>> '{context,action}' AS action
 FROM work_claims wc
 JOIN events e ON e.session_id = wc.session_id
 AND e.event_name = 'NextActionChosen'
 AND NULLIF(e.envelope, '')::jsonb #>> '{context,action}' <> 'charge'
 AND e.created_at > wc.claimed_at
 WHERE wc.released_at IS NULL
 ORDER BY wc.claimed_at
"

# Release a confirmed stranded claim (human-only override)
python3 -m yoke_core.api.service_client claim-release \
 --claim-id CLAIM_ID \
 --item-id YOK-N \
 --session-id SESSION_ID \
 --reason "offer-override cleanup"
```

## feed

```json
{
 "blocked_count": 2,
 "trigger": "drift_review",
 "drift_review": {
 "classification": "frontier_only",
 "summary": "2 delivered item(s) impact the frontier.",
 "checkpoint_start": "2026-04-01T12:00:00Z",
 "reviewed_through": "2026-04-05T16:42:00Z",
 "delivered_items": ["YOK-N", "YOK-N"]
 }
}
```

When the frontier also carries lane-filtered detail (current session's lane excludes some runnable work), the same `lane_filtered_count` / `lane_filtered_note` / `lane_filtered_items` keys attach to the `feed` context. The `trigger` field reports what caused FEED (`drift_review` or `no_runnable_items`) — lane filtering is additive context, not the trigger itself.

## strategize

```json
{
 "sml_coherent": false
}
```

## wait

```json
{
 "wait_seconds": 300,
 "retry_hint": "re-offer after cooldown"
}
```

### wait — no lane-compatible work

When the decision engine returns `wait` with `wait_reason: "no_lane_compatible_work"`, the frontier has items but the offering session's lane policy filters every one of them. Blocker-driven `escalate` retains precedence — this WAIT only fires when no blockers/exceptional items are present and the SML is coherent. The context carries the lane situation:

```json
{
 "wait_reason": "no_lane_compatible_work",
 "actual_lane": "ALTMAN",
 "lane_filtered_count": 2,
 "lane_filtered_note": "2 item(s) exist on the frontier but were filtered by lane policy — they may be runnable on another lane.",
 "lane_filtered_items": [
 {
  "item_id": "YOK-N",
  "title": "…",
  "status": "refined-idea",
  "next_step": "advance",
  "required_path": "advance",
  "rank": 0,
  "claim_state": "unclaimed"
 },
 {
  "item_id": "YOK-M",
  "title": "…",
  "status": "planned",
  "next_step": "shepherd",
  "required_path": "shepherd",
  "rank": 1,
  "claim_state": "unclaimed"
 }
 ],
 "lane_filtered_paths": [
 {"required_path": "advance", "count": 1},
 {"required_path": "shepherd", "count": 1}
 ]
}
```

`lane_filtered_paths` is a compact deterministic grouping of `lane_filtered_items[]` by `required_path` with counts; the loop renders it under a "Paths blocked for this lane" sub-heading so the operator sees at a glance which commands the current lane policy excludes. The lane-filtered keys (`lane_filtered_count`, `lane_filtered_note`, `lane_filtered_items`) also ride along with other outgoing actions (`escalate` with blockers, `feed` no-runnable, `feed` drift-review) whenever the frontier carries a non-zero filter count. The loop renders the note and item detail before invoking any follow-on handler.

This is distinct from `wait_reason="lane_policy_disallows_path"`, the tripwire used when a selected item or process action needs a path the actual lane does not allow. The process-action shape is documented below.

### wait — lane policy disallows process action

When the decision engine recommended a process-backed action (`feed` or `strategize`), the global `do_process_offer_*` policy enables that process, and the offering session's lane allowlist excludes the process token, the engine returns `wait` with `wait_reason="lane_policy_disallows_path"`. This is the process-action sibling of the lifecycle-path lane miss documented under `decide_charge_action` / `decide_resume_action`. If the global policy disables the same process, the policy branch wins instead and returns either a CHARGE fallback (when runnable work exists) or a suppressed-WAIT (when no runnable items exist) — see the next section.

```json
{
 "wait_reason": "lane_policy_disallows_path",
 "actual_lane": "ALTMAN",
 "required_path": "feed",
 "allowed_paths": ["refine", "polish"],
 "recommended_action": "feed",
 "process_key": "FEED",
 "original_reason": "No runnable items but strategy is coherent; materialize more work.",
 "original_context": {
  "blocked_count": 0,
  "trigger": "no_runnable_items"
 }
}
```

Lane WAITs do **not** carry `skipped_process` and are not recorded as disabled-process skip memory. Skip memory is reserved for `do_process_offer_*=false` policy blocks (see `session_decision_process_gate.record_disabled_process_skip`). Operators reading the WAIT need only the `actual_lane` + `required_path` pair to act: either widen the lane allowlist (`lane_paths_<lane>=...,feed`) or switch to a lane that already permits the path.

### wait — disabled process suppressed (no alternative)

When the decision engine recommended a process-backed action (`feed` or `strategize`), the global `do_process_offer_*` policy disables that process, AND no runnable items exist on the frontier, the engine returns a non-chainable `wait` with `wait_reason="process_suppressed_no_alternative"`. The recommendation surfaces as informational context under `suppressed_process_recommendation` instead of a terminal `escalate` — a disabled process is invisible to the decision engine, not a blocker. When runnable items exist, the policy branch takes the CHARGE-swap path documented above (the disabled process is recorded in skip memory and the chain continues).

```json
{
 "wait_reason": "process_suppressed_no_alternative",
 "suppressed_process_recommendation": {
  "process_key": "FEED",
  "config_key": "do_process_offer_feed",
  "config_source": "machine config",
  "recommended_action": "feed",
  "direct_command": "/yoke feed",
  "skip_reason": "process_disabled_by_config",
  "original_reason": "Drift review: frontier impacted. 49 delivered item(s) impact the frontier.",
  "original_context": {
   "blocked_count": 0,
   "trigger": "drift_review",
   "drift_review": { "...": "..." }
  }
 }
}
```

The `original_context` payload preserves `trigger="drift_review"` so `should_emit_drift_review_checkpoint` still advances the drift cursor on this path — drift-review threshold semantics are not regressed. The operator-facing `/yoke do` rendering names the suppressed recommendation, the disabling `config_key`, and the `direct_command` so the operator can run the direct command manually or flip the config flag in machine config.

## escalate

```json
{
 "blocked_items": ["YOK-N", "YOK-N"],
 "exceptional_items": ["YOK-N"],
 "blocked_details": [
 {
 "item_id": "YOK-N",
 "blocking_item": "YOK-N",
 "gate_point": "activation",
 "satisfaction": "status:done",
 "rationale": "YOK-N blocked at activation gate until YOK-N (Implement core API) satisfies status:done",
 "reason": "YOK-N is in status implementing, needs done"
 }
 ]
}
```

The `blocked_details` array is present when the shared scheduler provides structured blocker information. Each entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | string | The blocked item (``YOK-N``). |
| `blocking_item` | string | The blocker item (``YOK-N``). |
| `gate_point` | string | When the dependency matters: ``activation``, ``integration``, or ``closure``. |
| `satisfaction` | string | What must be true: ``status:done``, ``status:implemented``, or ``fact:merged``. |
| `rationale` | string | Persisted human-readable explanation of why this edge exists. |
| `reason` | string | Runtime evaluation: why the blocker is currently unsatisfied. |

When `blocked_details` is absent or empty, adapters should fall back to the `blocked_items` list for a simple enumeration of blocked item IDs. When the frontier also carries lane-filtered detail, the same `lane_filtered_count` / `lane_filtered_note` / `lane_filtered_items` keys ride along on `escalate` so the operator sees both signals.

## Item Execution-Status Diagnostics

When investigating why a routed action selected (or skipped) a particular item, the compact item execution-status read model surfaces the live facts that drove the decision without writing to the DB:

```bash
python3 -m yoke_core.domain.item_execution_status YOK-N            # text
python3 -m yoke_core.domain.item_execution_status YOK-N --json     # JSON
```

The projection composes existing item, work-claim, path-claim, Progress Log, File Budget, QA gate, and event facts into a single dict. It is read-only — never mutates rows, never parses chat-transcript text — and is the recommended diagnostic when a `/yoke do` chain ends in `escalate`, `wait`, or a `recoverable_substrate` skip and the operator needs to see what the loop saw.

The living execution-plan / journal projection is the future absorption target for this read model.
