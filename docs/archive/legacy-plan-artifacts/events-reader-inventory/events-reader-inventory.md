# B8 Phase 1 — Live `events`-Reader Inventory (G3.P5.I7)

Read-only analysis for the Wave 3 / B8 build phase: the `events` table becomes
telemetry-only; app-state reads are purged. Grounded against worktree
`g3w3-events-inventory` (main @ 32c5d4d37) and the live cloud-prod ledger
(2026-06-12; 1,400,832 rows).

Doctrine (G3.P5.I7): ALLOWED readers after B8 are telemetry/admin/query/
retention/audit-inspection surfaces. DISALLOWED: board/session/frontier/
idempotency/gate/provenance behaviors that infer application truth from events.

Classification rule applied: `app-state` when a runtime *behavior* (routing,
gating, rendering state, candidate selection, dispatch decision) changes based
on event rows; `audit/provenance` when an inspection surface (Doctor, audit
CLI) reads events to *report* on behavior; `telemetry-admin` when the reader
operates the ledger itself (query/tail/count/anomalies, registry, severity,
retention, pipeline-internal joins).

## Totals

| Class | Production modules | Notes |
|---|---|---|
| app-state (replace in B8) | 25 | direct `FROM events` SQL; +12 helper-mediated consumers inherit the cutover |
| audit/provenance (judgment per row) | 15 | Doctor HCs + audit engines; 2 contain dead branches |
| telemetry-admin (post-B8 allowlist) | 14 | query/registry/severity/retention/pipeline surfaces |
| emission-side probes | 2 | `SELECT 1 FROM events LIMIT 1` capability probes |
| test helpers / fixtures | 4 modules + ~60 test files | follow their production owner |
| teaching surfaces | 4 packet modules, 13 skills, 3 agent bodies, ~8 docs, AGENTS.md + Claude session rules | §4 |

## 1. app-state readers (must be replaced)

Format: reader → behavior → replacement (existing owner first, else smallest
new state) → write-path owner.

### Family 1 — Board activity + velocity

| # | Reader | Behavior | Replacement | Write owner |
|---|---|---|---|---|
| 1 | `runtime/api/board/activity_cache.py` (`_latest_activity_event_id`, `_query_activity_day_counts`) | Lifetime-activity % + streak: DISTINCT (day, item) over `ACTIVITY_EVENT_TYPES` (20 types, `activity_events.py`); `events.id` high-water mark = cache invalidation | New `item_activity_days` rollup `(project_id, item_id, day)` + monotonic version for invalidation; one-time backfill (§6) | Item-scoped domain actions that today emit activity events upsert the rollup (Risk R1 for tool-call attribution) |
| 2 | `runtime/api/board/widgets_velocity_meter.py` | Velocity widget: task-touch days (`event_type='task_status_change'`) + delivered (`ItemStatusChanged`/`TaskStatusChanged` → done/passed) | New `item_status_transitions` history table (shared with Family 2) | Lifecycle executor (`update_status` family) + epic-task status writer insert at mutation time |

`widgets.py`/`widgets_activity.py` consume `activity_cache` and inherit.

### Family 2 — Item execution/activity status

| # | Reader | Behavior | Replacement | Write owner |
|---|---|---|---|---|
| 3 | `runtime/api/domain/item_execution_status_helpers.py` (latest event per item) | `item_execution_status` read-model "events" section (latest event name/severity/age) | latest `item_status_transitions` row + Family 3 activity columns | as #2 |
| 4 | `runtime/api/domain/backlog_github_body_budget.py` (`_evidence_summary`) | Compact GitHub mirror renders "recent evidence" from latest item event | latest `item_status_transitions` row | as #2 |
| 5 | `runtime/api/domain/backlog_github_sync_cli.py` (`_select_event_derived_candidates`) | Sync candidate selection scans `HarnessToolCallCompleted` envelopes for a body-too-long marker — a work queue inferred from telemetry | Item-side flag (e.g. `github_body_compact_pending` on `items` or a sync-state row) | `backlog_github_body_budget` budget-violation path sets; sync clears |

### Family 3 — Session liveness, reclaim, cleanup, reactivation, orphan sweep, claim-acquire freshness

Live schema check (cloud-prod): `harness_sessions` has NO tool-activity,
episode, or resume-notice columns; `work_claims` has NO claim-reason or
release-intent columns. The events ledger is the ONLY store for these today.

| # | Reader | Behavior | Replacement | Write owner |
|---|---|---|---|---|
| 6 | `runtime/api/domain/session_reclaim_activity.py` (`_max_tool_event_at` → `latest_activity`) | THE activity hub: MAX(created_at) of `HarnessToolCallCompleted/Failed` per session. Fans out to `scheduler_claims` (stale reclaim), `sessions_render_reclaim(_item)`, `chain_head_freshness`, `sessions_cleanup`, `harness_sessions_claims_acquire`, `item_execution_status`, `doctor_hc_agents_sessions` | `harness_sessions.last_tool_call_at` | Observe pipeline (`observe.py`/`observe_event_emission.insert_event` call sites) updates in same txn as telemetry insert |
| 7 | `runtime/api/domain/sessions_cleanup.py` (tool count + latest per session) | 30-min stale sweep; `never_engaged` needs "zero tool calls ever" | + `harness_sessions.tool_call_count` (or `first_tool_call_at`) | as #6 |
| 8 | `runtime/harness/harness_sessions_claims_acquire.py` (MAX tool event per conflicting session) | Claim-acquire conflict freshness: reclaim-vs-refuse | `last_tool_call_at` | as #6 |
| 9 | `runtime/harness/harness_sessions_inventory.py` (NOT EXISTS events since cutoff) | Stale-session inventory listing | `last_tool_call_at` | as #6 |
| 10 | `runtime/api/domain/sessions_lifecycle_reactivation.py` (`SessionReactivatedWithReleasedClaims`/`HarnessSessionResumeBlockShown`/`SessionReactivationReacquiredClaims` scan) | Pending "SESSION RESUMED" block: render-once state machine stored as events | `harness_sessions.pending_resume_notice` JSON (written at reactivation, cleared at render) | `register_session` reactivation writes; hook-runner render clears |
| 11 | `runtime/api/domain/sessions_orphan_tool_call_sweep.py` (Started-without-Completed) | Session-end sweep synthesizes completion events so activity/duration stay sane | New `session_tool_calls` rolling state table (session_id, tool_use_id, tool_name, started/completed_at, outcome, command summary; short retention). Open rows = orphans; sweep becomes table maintenance (Risk R3) | Observe pipeline inserts on Started, completes on Completed/Failed |
| 12 | `runtime/api/domain/events_current_episode.py` (`resolve_current_episode_boundary` over `HarnessSessionResumed/Started`) | Episode boundary = session truth from events; consumed by `harness_sessions_claims` (`who-claims --current-episode`) + `sessions_lifecycle_resumption_emit` | `harness_sessions.episode_started_at` (set at register + resume) | `register_session`/resumption path |
| 13 | `runtime/api/domain/lint_claim_ownership_mutations.py` (recent session Bash completions) | PreToolUse guardrail gates on recent command history | `session_tool_calls` (needs command text — Risk R4) | as #11 |
| 14 | `runtime/api/domain/lint_long_command_polling_evaluate.py` (recent Bash tool calls) | Polling-loop deny gate | `session_tool_calls` | as #11 |
| 15 | `runtime/api/domain/lint_long_command_polling_monitor_duplicate.py` (Monitor `HarnessToolCallStarted` rows) | Duplicate-Monitor-arming deny gate | `session_tool_calls` | as #11 |

### Family 4 — Dispatcher idempotency

| # | Reader | Behavior | Replacement | Write owner |
|---|---|---|---|---|
| 16 | `runtime/api/domain/yoke_function_dispatch.py` (`_idempotency_lookup`: last 200 `YokeFunctionCalled` envelopes scanned for `context.request_id`) | Replay/collision decision per function call | New `function_call_ledger`: `request_id` unique, `function_id`, `result` JSON, `created_at`; TTL prune | Dispatcher writes alongside `emit_function_called` (`yoke_function_dispatch_events`) |

### Family 5 — Frontier/recent-owner and chain/task freshness

| # | Reader | Behavior | Replacement | Write owner |
|---|---|---|---|---|
| 17 | `runtime/api/domain/frontier_recent_owner.py` (`WorkReleased` → `context.release_reason_intent`) | `routed_ownership_exclusions` — frontier routing + offer-lane defense (`frontier_compute`, `sessions_offer_ownership_guard`, `sessions_offer_envelope_merge`, `service_client_ownership_guard`) | `work_claims.release_reason_intent` column (`release_reason` exists; intent lives only in the event) | Release path (`sessions_lifecycle_release`) |
| 18 | `runtime/api/domain/idea_claim_events.py` (`_lookup_claim_reason_intent`: `WorkClaimed` envelope by claim_id) | At release, recovers why the claim was acquired (idea-release classification/emission) | `work_claims.reason` + `reason_intent` written at acquire | `claims.work.acquire` path |
| 19 | `runtime/api/domain/chain_head_freshness.py` (`latest_task_event_at` for `(item_id, task_num)` + `latest_activity`) | `/yoke conduct` re-entry: resumable/busy/blocked | Task half: `epic_tasks.last_activity_at` (or latest task transition row); session half: `last_tool_call_at` | Epic-task mutation paths stamp `last_activity_at` |
| 20 | chain reads in `doctor_hc_routed_ownership.py` (MAX step / last checkpoint from `ChainStepCompleted`; last `HarnessSessionOffered`) | Stuck-routed-session detection (audit surface, but chain state has no table owner) | `harness_sessions.last_chain_step` + `last_checkpoint_at` (offer time derivable from `offered_at`/`offer_envelope`) | Chain checkpoint handler (the `ChainStepCompleted` emitter) |

### Family 6 — DB-claim prose gate

| # | Reader | Behavior | Replacement | Write owner |
|---|---|---|---|---|
| 21 | `runtime/api/domain/db_claim_prose_check_state.py` (`_read_latest_reviewed_negative_claim_event`: latest completed `DbClaimAmended` with `new_profile.state=='none' && validation_result=='pass'`) | Prose-vs-claim gate escape hatch (`db_claim_prose_check` + `_triggers`) | Attestation into `items.db_mutation_profile` JSON (e.g. `reviewed_negative` + `validated_at`) — column exists; only the reviewed bit lives in events | `db_claim.amend` handler stamps at amend time |

### Family 7 — Path context / continuity / override provenance

| # | Reader | Behavior | Replacement | Write owner |
|---|---|---|---|---|
| 22 | `runtime/api/domain/path_claims_override.py` (`list_override_events`/`is_active_override` over `PathClaimOverride`, 29 rows) | `is_active_override` GATES overlap classification (`path_claims_overlap`, `path_claims_read`, `idea_readiness_repair_cross_item_overlap`, `handlers/claims_path`) — a live gate, sharper than provenance | New `path_claim_overrides` table (claim ids, operator, reason, created_at); evidence rendering re-points | `invoke_override` (`path_claims_dispatch_override`) |
| 23 | `runtime/api/domain/path_context.py` (`_verify_event_exists`) | Context authoring REQUIRES `recorded_event_id` in events — correctness depends on telemetry + retention (WARN pruned 90d) | Drop live FK verification (keep opaque provenance string) or copy provenance at write. Recommend drop: retention already makes it unsound (Risk R5) | n/a |
| 24 | `runtime/api/domain/path_continuity.py` (`_verify_event_exists`) | Same contract for continuity | Same as #23 | n/a |

`path_integrity_fixtures_helpers.py` (fixture inserting events rows for the FK)
follows #23/#24.

### Family 8 — Deployment/run evidence (FINDING: already dead)

| # | Reader | Live evidence | Disposition |
|---|---|---|---|
| 25 | `runtime/api/engines/done_transition_deploy_gates.py` (`event_type='deployment'` fallback + `_count_deployment_events`) | **0 rows in 1.4M** — fallback can never pass | DELETE fallback; `deployment_runs`/`deployment_run_items` already own the concept |
| — | `runtime/api/engines/resync_doctor_output.py` (`event_type='sync_failure'`, 2 sites) | **0 rows** | DELETE or re-point at a real sync-failure store |
| — | `runtime/api/engines/doctor_hc_db_project_orphans.py` (deployment-event branches) | **0 rows** | DELETE the deployment branch |

### Plan-missed app-state reader

| # | Reader | Behavior | Replacement | Write owner |
|---|---|---|---|---|
| 26 | `runtime/api/domain/drift_review.py` (checkpoint = MAX `StrategizeCompleted`/`DriftReviewCompleted` per project, 28 rows; delivered-since = `ItemStatusChanged` → release/done) | Drift-review scoping decisions | New `strategy_checkpoints` (project_id, kind, created_at); delivered-since re-points at `item_status_transitions` | strategize/drift-review completion paths |

Also missed by the plan (rows above): #4–5 (GitHub sync), #13–15 (lint
guardrails), #18 (claim reason recovery), #12 (episode boundary).

## 2. audit/provenance readers (judgment calls)

| Reader | What it reads | Recommendation |
|---|---|---|
| `runtime/api/engines/doctor.py` | `HarnessSessionEndDeferred` without later `Ended` (20 rows) | Keep-as-audit; optional `harness_sessions.deferred_end_pending` re-point later |
| `doctor_hc_agents_sessions.py` | sweep-ran marker; `WorkReclaimed` + post-reclaim activity | Keep-as-audit (verifying behavior against telemetry is the point); activity check may re-point at `session_tool_calls` |
| `doctor_hc_stop_hook_chain.py` | `ChainEndDeferred` without `HarnessSessionEnded` | Keep-as-audit; re-point when chain state lands |
| `doctor_hc_routed_ownership.py` | WorkReleased intent + ChainStepCompleted subqueries | Re-point with Slice D (mirrors `frontier_recent_owner` exactly) |
| `doctor_hc_skip_bypass.py` | ItemStatusChanged 30d to_status/source | Re-point at `item_status_transitions` (Slice C) |
| `doctor_hc_meta_lifecycle.py` | items without matching ItemStatusChanged | Re-point at `item_status_transitions`; ledger cross-check version may retire |
| `doctor_hc_session_cwd_binding.py` | last 5 `HarnessToolCallStarted` envelopes; tool counts | Keep-as-audit; may re-point at `session_tool_calls` |
| `doctor_hc_path_claim_rejections.py` | `PathClaimRegistrationBlocked` 24h summary | Keep-as-audit |
| `doctor_hc_apply_patch.py` | apply_patch presence in envelopes | Keep-as-audit |
| `doctor_hc_reflection_capture_hook_coverage.py` / `_persist_failed.py` | hook-coverage / persist-failure audit | Keep-as-audit |
| `check_claim_boundary_audit_correlation.py` / `_cutoff.py` (+ `doctor_hc_claim_boundary_audit.py`) | HarnessToolCall ↔ YokeFunctionCalled correlation | Keep-as-audit (the audit-inspection carve-out) |
| `resync_doctor_output.py` / `doctor_hc_db_project_orphans.py` dead branches | 0-row shapes | Delete (Family 8) |

## 3. telemetry-admin readers (post-B8 allowlist)

- `events_queries.py` — `events list/count/anomalies/tail/query` + `_build_where`.
- `handlers/events_reads.py` — `events.query/tail/count/anomalies` function ids.
- `events_audit_presets.py` — `--failed-only` / `--friction-summary`.
- `events_prune.py` — severity retention (DELETE).
- `events_registry_audit.py` + `doctor_hc_db_events_registry.py` — registry drift.
- `tools/backfill_event_severity.py` — severity relabel.
- `doctor_hc_db_catalog.py`, `doctor_hc_db_events_emission.py`,
  `doctor_hc_db_events_ledger.py` — ledger hygiene (contamination, rate, lineage).
- `doctor_hc_event_outcome_drift.py`, `doctor_hc_event_outcome_enum_coverage.py`,
  `doctor_hc_event_severity_drift.py` — enum/severity drift.
- `observe_normalization.py` (`_compute_duration` joins Started by tool_use_id)
  — pipeline-internal; allowed. Optional: read `session_tool_calls.started_at`
  once Slice A lands.
- `events_current_episode.py` — the `events list --current-episode` FILTER use
  stays; boundary RESOLUTION moves to the session column (#12).

Emission-side probes (`SELECT 1 FROM events LIMIT 1`): `epic_cascade.py`,
`observe_event_emission.insert_event` — write-path capability probes, keep.

## 4. Teaching surfaces

App-state event-read teachings (purge/re-teach in build phase):

| Surface | Teaching | Disposition |
|---|---|---|
| `schema_api_context_tables_core.py` events entry (~L195-208) | Recipes: ItemStatusChanged status reads, WorkClaimed per item, envelope from/to_status | Rewrite telemetry-only + point app-state questions at new tables |
| `.agents/skills/yoke/approve/SKILL.md:83` | Deploy verification via `DeploymentRunStageCompleted` envelope query | Re-teach against `deployment_runs`/`deployment_run_items` |
| `.agents/skills/yoke/usher/SKILL.md:30` | "Query events for verification before advancing past deployment gates" | Same re-teach |
| `.agents/skills/yoke/strategize/refresh.md:14` | `StrategizeCompleted` checkpoint freshness from events | Re-teach against `strategy_checkpoints` |
| `AGENTS.md`/`CLAUDE.md` | "History: `events list --event-name DbClaimAmended`" | Keep with one-line reword (history-only once attestation lives on profile) |
| `runtime/harness/claude/rules/session.md` | `events list --event-name HarnessSessionEndDeferred` investigation | Keep (audit use) |
| `.agents/skills/yoke/conduct/{dispatch-context,engineer-tester-loop,entry-activation-resolution}.md` | reference `chain_head_freshness` module, not raw SQL | Keep; verify wording post-cutover |
| `.agents/skills/yoke/feed/summarize.md:217` | names FeedCompleted row as output | Keep (emission) |

Telemetry-forensic teachings that STAY: skills `advance`, `curate`, `doctor`,
`idea`, `polish`, `refine`, `shepherd`, `simulate`, `wrapup` (events
tail/anomalies/query for diagnosis); agent bodies `engineer.md`, `tester.md`,
`simulator.md`; docs `structured-logging-standard*`, `event-contract/*`,
`admin/break-glass.md`, `archive/events-incident-followup.md`.
`sql_json.py`/`time_sql.py` docstring examples are cosmetic; reword
opportunistically.

## 5. Emission-side cleanup targets

| Wrapper | Disposition |
|---|---|
| `events.py` (`emit_event`) + `events_insert_sql.py` + `events_writes.py` | Already-canonical — THE emission path |
| `runtime/harness/hook_runner/telemetry.py` | Already-canonical re-export shim + 3 runner-native emitters; same-object mock semantics documented |
| `observe_event_emission.py` + `observe_pre.py` (direct `insert_event`) | Adapt: highest-volume writer (HarnessToolCall* ≈ 486k rows) gains the Slice A state writes; converging onto `emit_event` optional, state-write hook mandatory |
| `yoke_function_dispatch_events.py` | Adapt: add `function_call_ledger` write next to `YokeFunctionCalled` |
| `qa_events.py`, `scheduler_events.py` | Already-canonical (route through emit_event) |
| `harness_sessions_event_emit.py` | Adapt: acquire/release sites add the new `work_claims` column writes (Slice D) |
| `activity_events.py` | Delete or repurpose as the rollup trigger set once board cuts over |
| `templates/events/` (py/ts emitters, api-route, props/types/attribution) | Keep as reference emitters; no app-state read recipes found |
| `epic_cascade.py` probe | Keep/simplify |

97 modules import `emit_event` overall — emission stays first-class; only the
named wrappers above need adapt/delete decisions.

## 6. Live row volumes + backfill sources (cloud-prod, 2026-06-12)

Total **1,400,832**. Top: HookDispatchTelemetry 467,711; HookGuardrailEvaluated
339,675; HarnessToolCallCompleted 264,543; HarnessToolCallStarted 214,328;
HookExecutionFailed 12,034; YokeFunctionCalled 10,971; ItemStatusChanged
7,664; HarnessToolCallFailed 7,211; HarnessSessionStarted 6,477; TaskStatusChanged
5,509; ChainStepCompleted 3,326; WorkClaimed 2,279; WorkReleased 1,900;
HarnessSessionOffered 1,732. Low-volume backfill names: DbClaimAmended 328,
DeploymentRunStageCompleted 336, SessionReactivatedWithReleasedClaims 156,
HarnessSessionResumed 110, PathClaimOverride 29, HarnessSessionEndDeferred 20,
DriftReviewCompleted 15, StrategizeCompleted 13, WorkReclaimed 10. Dead shapes:
`event_type='deployment'` **0**, `event_type='sync_failure'` **0**.

Draft one-time backfill source queries (run inside governed migrations):

```sql
-- harness_sessions.last_tool_call_at
SELECT session_id, MAX(created_at) FROM events
 WHERE event_name IN ('HarnessToolCallCompleted','HarnessToolCallFailed')
   AND session_id IS NOT NULL GROUP BY session_id;
-- harness_sessions.episode_started_at
SELECT session_id, MAX(created_at) FROM events
 WHERE event_name IN ('HarnessSessionResumed','HarnessSessionStarted')
 GROUP BY session_id;
-- item_status_transitions (13,173 rows; envelope JSON tolerant of
-- $.context.detail / $.context / $ nesting variants)
SELECT item_id, task_num, event_name, session_id, actor_id, project_id,
       envelope, created_at FROM events
 WHERE event_name IN ('ItemStatusChanged','TaskStatusChanged');
-- item_activity_days rollup (one 1.4M-row scan)
SELECT project_id, item_id, (created_at)::date AS day FROM events
 WHERE item_id IS NOT NULL AND event_type IN (<ACTIVITY_EVENT_TYPES>)
 GROUP BY 1, 2, 3;
-- work_claims.reason/reason_intent (2,279; key $.context.detail.claim_id)
SELECT envelope FROM events WHERE event_name = 'WorkClaimed';
-- work_claims.release_reason_intent (1,900; key $.context.claim_id)
SELECT envelope FROM events WHERE event_name = 'WorkReleased';
-- session chain state (3,326)
SELECT session_id, MAX(CAST(envelope #>> '{context,step}' AS INTEGER)),
       MAX(created_at) FROM events
 WHERE event_name = 'ChainStepCompleted' GROUP BY session_id;
-- db_mutation_profile reviewed-negative attestation (328; latest per item)
SELECT DISTINCT ON (item_id) item_id, envelope, created_at FROM events
 WHERE event_name = 'DbClaimAmended' AND event_outcome = 'completed'
 ORDER BY item_id, created_at DESC, id DESC;
-- path_claim_overrides (29) / strategy_checkpoints (28)
SELECT envelope, created_at FROM events WHERE event_name = 'PathClaimOverride';
SELECT envelope, created_at FROM events
 WHERE event_name IN ('StrategizeCompleted','DriftReviewCompleted');
-- function_call_ledger seed (optional ~7d; live window is only last 200 rows)
SELECT envelope, created_at FROM events
 WHERE event_name = 'YokeFunctionCalled' AND created_at >= <now-7d>;
```

All backfills MUST filter known contamination (`session_id LIKE 'test-%'`,
`'sess-%'`, `'dup'`, synthetic `anomaly_flags`) — the §3 hygiene HCs document
the live contamination classes.

## 7. Proposed build-phase slice partition (5 slices)

Each slice owns its reader cutovers, write-path hooks, tests, and the teaching
purge for ITS surfaces. Yoke is `founder_cutover`; every migration below is
schema-`additive_only` (new tables/columns + one-time data load) — the cutover
is in code; the events table is untouched.

- **Slice A — Session & tool-call activity state (largest).** Tables:
  `harness_sessions` + `last_tool_call_at`/`tool_call_count`/
  `episode_started_at`/`pending_resume_notice`; new `session_tool_calls`
  rolling table. Write hooks: observe pipeline, `register_session`/
  reactivation, orphan sweep → table maintenance. Readers: #6–15 (+ optional
  doctor re-points). Tests: `test_sessions_cleanup*`,
  `test_sessions_orphan_tool_call_sweep`,
  `test_sessions_claims_acquire_reclaim_abort`,
  `test_sessions_lifecycle_reactivation_claims`,
  `test_events_queries_current_episode`, lint suites. Migration: governed
  additive + backfill. If it must split, lints #13–15 trail safely (fail-open).
- **Slice B — Function-call idempotency ledger (smallest).** Table:
  `function_call_ledger` + TTL prune. Write hook: dispatcher. Reader: #16.
  Tests: dispatcher idempotency suite. Migration: additive; thin/no seed (live
  window ≈ last 200 events). Zero file overlap — good first slice.
- **Slice C — Item/task transition history + board + drift.** Tables:
  `item_status_transitions`; `item_activity_days` (or explicit
  reduced-semantics decision, R1); `strategy_checkpoints`. Write hooks:
  lifecycle executor + epic-task status writer; rollup upserts in item-scoped
  actions; strategize/drift completion. Readers: #1–4, #26; re-point
  `doctor_hc_skip_bypass`, `doctor_hc_meta_lifecycle`. Tests: board
  widget/activity-cache, drift_review, `test_update_status_full_lifecycle`,
  doctor HC tests. Migration: additive + the largest backfill (13k transitions
  + one 1.4M-row rollup scan).
- **Slice D — Claim/frontier/chain state columns.** Columns:
  `work_claims.reason`/`reason_intent`/`release_reason_intent`;
  `harness_sessions.last_chain_step`/`last_checkpoint_at`;
  `epic_tasks.last_activity_at`. Write hooks: claim acquire/release, chain
  checkpoint handler, epic-task mutations. Readers: #17–20 +
  `doctor_hc_routed_ownership`. Tests: frontier/offer suites
  (`test_sessions_offer_lane_anchor`, `test_service_client_sessions_offer*`),
  chain-head, routed-ownership HC. Migration: additive + envelope backfills.
  Shared-file caution vs Slice A (`harness_sessions` columns + session files):
  run AFTER A or merge migration modules.
- **Slice E — Gates, provenance, dead code, teaching sweep.** DB-claim
  attestation into profile (+328-event backfill, reader #21); `path_claim_overrides`
  table (+29 backfill, reader #22); path context/continuity verification
  decision (#23–24 + fixture helper); GitHub-sync items-side flag (#5, and #4
  consumes C's table — E after C); DELETE dead readers (#25 family); teaching
  sweep (§4) + final repo grep that every remaining `FROM events` reader is on
  the §3 allowlist. Migration: additive (two small backfills).

Order: B → A → C → D → E. A/B/C are file-disjoint (parallel worktrees OK);
D after A; E last.

## 8. Governed-migration needs

All five slices declare `migration_model` work: new tables/columns + one-time
backfills from the ledger (§6). Strategy `additive_only` each — no existing
schema surface is replaced; B8's read purge needs NO destructive change to
`events`. Later retention tightening (e.g. the 800k hook-telemetry rows) is
operator policy, not B8 scope.

## 9. Biggest risks (semantics a table can't trivially replicate)

- **R1 — Board lifetime-activity semantics.** "Touched" = ANY of 20
  heterogeneous event types with item_id (incl. `tool_call`,
  `session_lifecycle`). A mutation-time rollup means many write sites; a single
  chokepoint inside `emit_event` would make STATE depend on the telemetry
  pipeline — the exact inversion B8 removes. Options: (a) reduced semantics
  (transitions + claims + structured writes), (b) wire rollup into item-scoped
  domain actions individually. Note: retention ALREADY decayed current
  semantics (INFO dies at 30d) — historical agent-activity days survive only
  via the one-time backfill either way.
- **R2 — Idempotency window change.** Today: last-200-events global scan
  (time-unbounded under low traffic, racy under high) with cross-function
  collision detection. Ledger: exact match + TTL — strictly better, but replay
  must preserve the stored `context.result` shape bit-for-bit and keep the
  `idempotency_key_collision` error.
- **R3 — Orphan sweep double bookkeeping.** The sweep currently REPAIRS
  telemetry (synthesizes completion events). With `session_tool_calls` as
  state, decide whether synthetic completion EVENTS are still written (ledger
  hygiene/duration stats) or the ledger tolerates orphans. Silent table-vs-
  ledger divergence is the failure mode.
- **R4 — Lint guardrails need command text.** #13–15 scan envelope
  `tool_input.command`; `session_tool_calls` must carry a command/summary
  column (bounded retention, partially duplicating telemetry) or lints keep a
  degraded signal. They fail open — trailing cutover safe.
- **R5 — Provenance FK vs retention.** `path_context`/`path_continuity`
  REQUIRE `recorded_event_id` to exist; WARN pruning at 90d already makes this
  unsound. Dropping verification weakens the authoring-time guarantee; copying
  provenance at write is the alternative. Needs a decision record.
- **R6 — Backfill contamination.** The ledger contains known synthetic/test
  rows; every backfill filters them or the state tables inherit garbage with
  no second chance post-retention.
- **R7 — Episode-boundary history.** `who-claims --current-episode` reports
  `unknown` for sessions outside the backfill window unless the backfill covers
  all sessions (it can — boundary names are STATUS-severity, retained forever).

## 10. Contradictions vs plan expectations

- **Family 8 (deployment evidence) is already dead, not live.**
  `event_type='deployment'` and `sync_failure` have ZERO rows;
  `deployment_runs` already owns the concept. B8 work is deletion, not
  replacement — no deployment-evidence state table needed.
- **The claim-reason concept has NO table owner at all** (`work_claims` lacks
  both `reason` and intent columns) — a column addition + acquire-path write,
  not just a read cutover.
- **The DB-claim gate needs no new table** — the profile JSON column exists;
  only the reviewed-negative attestation bit lives in events.
- **Three PreToolUse lint guardrails** gate on event rows and were unnamed in
  the plan's family list, as was **GitHub sync using telemetry as a work
  queue** (body-too-long marker scan).
- **`events_current_episode`** powers an allowed audit filter AND a
  session-truth resolver — it splits across classes rather than landing in one.
