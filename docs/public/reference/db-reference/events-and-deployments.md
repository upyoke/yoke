# DB Reference — Events, Severity Config, Deployment Runs

Schemas for the unified events log, write-side severity config and registry, deployment runs, run/item membership, run-level QA, and ephemeral / preview environment tracking. Cross-link back from [db-reference.md](../db-reference.md) for entry points, the domain catalog, timestamp discipline, JSON-payload conventions, qa CLI, body write path, and the status lifecycle reference.

## Table: events

Cross-stack structured event log. Unified envelope for agent tool calls, session lifecycle, backend telemetry, frontend analytics, and system events. All source types share the same schema, enabling cross-source queries on a single table. Workbench analytics use the anonymous `/api/events` collector; [workbench telemetry](../../events-doctor-ouroboros.md) explains consent, admission, URL hygiene, packaging, and durable `actors.attribution` ownership.

Compatibility note: first-class tool-call correlation columns are optional across local installs and emitters. Readers and emitters must tolerate their absence until all live event tables expose the full correlation surface.

```sql
id INTEGER PRIMARY KEY
event_id TEXT UNIQUE NOT NULL -- UUID, deduplication key (ON CONFLICT DO NOTHING)
source_type TEXT NOT NULL -- 'agent' | 'backend' | 'frontend' | 'system' | 'script' | 'hook' | 'skill'
session_id TEXT NOT NULL -- session/request correlation ID
severity TEXT NOT NULL DEFAULT 'INFO' -- DEBUG | INFO | WARN | ERROR | FATAL
event_kind TEXT NOT NULL -- taxonomy tier 1 (e.g., 'system', 'domain', 'user')
event_type TEXT NOT NULL -- taxonomy tier 2 (e.g., 'tool_call', 'session')
event_name TEXT NOT NULL -- PascalCase event name (e.g., 'HarnessToolCallCompleted')
event_outcome TEXT -- nullable outcome (e.g., 'completed', 'failed')
org_id TEXT -- organization identifier
actor_id INTEGER -- nullable Yoke control-plane subject; references actors(id)
environment TEXT -- runtime environment (e.g., 'dev', 'prod')
service TEXT NOT NULL DEFAULT 'cli' -- emitting service
project_id INTEGER -- nullable project context; references projects(id); no implicit attribution
item_id TEXT -- owned backlog join key; public reads project it to public_ref
task_num INTEGER -- epic task number
agent TEXT -- agent role (e.g., 'engineer', 'tester')
tool_name TEXT -- tool that was called (e.g., 'Bash', 'Read')
duration_ms INTEGER -- execution duration in milliseconds
exit_code INTEGER -- process exit code
trace_id TEXT -- distributed trace ID
anomaly_flags TEXT -- → JSONB on Postgres (array shape); today a comma-separated anomaly-flag list per `docs/event-contract.md` (e.g., 'nonzero_exit,retry_loop')
tool_use_id TEXT -- target first-class dedup key for tool-call events; current live coverage is still incomplete
client_timing_id TEXT -- key a hook client minted for its own dispatch, so the wall time it reports afterwards finds this row by index; cleared once that report lands
envelope TEXT -- → JSONB on Postgres; full JSON envelope for lossless storage
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

**Indexes:** `source_type`, `session_id`, `event_name`, `created_at`, `actor_id`, `trace_id`, `project_id`, `tool_name`, `(event_kind, event_type)`, plus the partial dedup index `(tool_use_id, event_name) WHERE tool_use_id IS NOT NULL` and the partial correlation index `(client_timing_id) WHERE client_timing_id IS NOT NULL` on DBs with the full correlation surface. Correlate through an indexed column; matching a substring of `envelope` with LIKE has no index to use and reads every row the other predicates admit.

Event reads project nested envelope item identities and item history `target_id` to complete public refs; storage keeps owned join keys. Other record IDs retain their domain meaning.

Engine identity is actor-only. Historical JSON envelopes may retain a null human-user key, but fresh schemas, writers, readers, and filters do not expose that retired surface.

**Deduplication:** The `event_id` column has a UNIQUE constraint. Inserts use `ON CONFLICT DO NOTHING` so duplicate event IDs are silently dropped.

**Write-side severity filtering:** Before inserting, events are checked against the `severity_config` table. Events below the configured minimum severity for their `(event_name, source_type)` pair are silently dropped without error. The acknowledged anonymous frontend collector bypasses this optional filter; retention still applies.

**Retention (prune):** DEBUG=1d, INFO=30d, WARN=90d, STATUS/ERROR/FATAL=forever. Event preview and delete are LIMIT-batched (`--batch-size`, default 1000). LIMIT caps matching rows, not scanned rows or query duration; the monotonic `--max-seconds` deadline (default 30) is checked between statements, and each event count/delete/leftover probe sets `statement_timeout` to the remaining budget so a sparse scan, `ORDER BY`, or leftover peek cannot outlive the pass. That timeout is event-only: after each event probe it is restored to the incoming `SHOW statement_timeout` (not forced to zero) before ledger, dispatch-intent, and `session_tool_calls` helpers, which keep their existing retention contracts. Optionally batch-capped (`--max-batches`); counts are exact or labeled `>=N (partial)`. A statement timeout is a graceful stop: already-committed batches stay. Referenced `event_id` rows (path-audit tables) are kept on every event delete path. Obsolete-name cleanup is opt-in (`--purge-obsolete`). Live invocation: `python3 -m yoke_core.cli.db_router events prune [--dry-run]`. Rerun after `stopped: batch/time budget`. No automatic prune timer lives in this repo; do not invent a parallel scheduler. DEBUG is the on-demand-capture tier (dropped at the default INFO write floor; enable by lowering `severity_config` to DEBUG), so it carries the shortest retention.

## Table: severity_config

Write-side severity filtering configuration for the events table. Controls which severity levels are persisted per event name and source type combination.

```sql
id INTEGER PRIMARY KEY
event_name TEXT NOT NULL DEFAULT '*' -- event name pattern ('*' = wildcard)
source_type TEXT NOT NULL DEFAULT '*' -- source type pattern ('*' = wildcard)
min_severity TEXT NOT NULL DEFAULT 'INFO' -- DEBUG | INFO | WARN | ERROR | FATAL
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
UNIQUE(event_name, source_type)
```

**Lookup order:** exact `(event_name, source_type)` > `(event_name, *)` > `(*, source_type)` > `(*, *)`. First match wins. Seeded with catch-all `(*, *, INFO)` on init.

## Table: event_registry

Central registry of all known event types. Governs event naming, ownership, and lifecycle. Used by `yoke_core.domain.observe` (lint-event-registry guardrail) (PreToolUse hook) and doctor health checks to enforce event governance.

```sql
event_name TEXT PRIMARY KEY -- PascalCase event name (e.g., 'HarnessToolCallCompleted')
event_kind TEXT NOT NULL -- taxonomy tier 1 (e.g., 'system', 'domain')
event_type TEXT NOT NULL -- taxonomy tier 2 (e.g., 'tool_call', 'session')
owner_service TEXT NOT NULL -- emitting service (e.g., 'yoke_core.domain.observe')
description TEXT NOT NULL -- human-readable description
context_schema TEXT -- optional JSON schema for context payload
severity_default TEXT NOT NULL DEFAULT 'INFO' -- default severity level
added_in TEXT -- PREFIX-N or version when added
status TEXT NOT NULL DEFAULT 'active' -- 'active' | 'deprecated'
```

**Idempotent writes:** `registry add` uses `ON CONFLICT DO NOTHING` semantics — duplicate `event_name` inserts silently succeed (exit 0, no row change). This makes `python3 -m yoke_core.domain.populate_registry` safe to re-run.

**Lifecycle:** Events start as `active`. Use `registry deprecate <name>` to mark events no longer emitted. The `registry audit` subcommand reports stale active entries (registered but not emitted in 30 days) and rogue events (emitted but not registered).

## Table: deployment_runs

One row per pipeline execution. Stage authority lives on the run, not on individual items. A run may be item-bound through `deployment_run_items`, or item-less for environment-level deploys such as Yoke prod/stage redeploys.

```sql
id TEXT PRIMARY KEY -- human-readable slug (e.g., 'run-20260315-001')
project_id INTEGER NOT NULL REFERENCES projects(id)
flow TEXT NOT NULL REFERENCES deployment_flows(id)
target_tier TEXT -- persistent | ephemeral | NULL (merge-only)
target_environment_id INTEGER -- internal REFERENCES environments(id); required exactly when target_tier='persistent'
release_lineage TEXT -- links preview->prod runs (shared lineage ID)
status TEXT NOT NULL DEFAULT 'created' -- created|executing|succeeded|failed|cancelled
current_stage TEXT -- stage authority lives here, not on items
current_stage_entered_at TEXT -- clock set when the stage changes; NULL means unknown age, no backfill
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
started_at TEXT -- when execution actually began
completed_at TEXT
created_by TEXT -- 'operator' or 'system'
carried_work TEXT -- → JSONB on Postgres; resolved items, release output, and unresolved commit SHAs with subjects
artifact_identity TEXT -- optional immutable build artifact identity, distinct from release_lineage
composition_resolution TEXT -- explicit first-baseline attribution resolution
composition_frozen_at TEXT -- immutable admission-freeze timestamp
requirement_snapshot TEXT -- full flow-level QA plan/case content frozen at start
```

A run copies the internal `target_tier` and `target_environment_id` from its flow. Operators select or override a persistent target only with `--environment <registered-name>`; numeric keys are never accepted or emitted by the operator surface. Setting `status=succeeded` stamps `environments.last_deployed_at` on the referenced row.

Succeeded completion and composition freeze always record `carried_work`. A failed or cancelled transition (operator terminalization included), and a Shipping or Runs read that finds a terminal run unrecorded, record it only when the answer is permanent: derived, or unknown for a reason that is a fact about the run's own record (`current_release_lineage_missing`, `prior_release_lineage_missing`, `release_lineages_diverged`, or a lineage a fully refreshed source cannot resolve). A failure the environment caused — fetch, provider, network, credential, missing checkout, or an ancestry read git could not complete (`checkout_ancestry_unreadable`, never reported as divergence) — returns its named unknown answer unrecorded and is derived again on a later read. **A read may therefore write:** `deployment_runs.list` and the Runs page commit that one derived field on their own connection, so any actor allowed to read a run can cause its carried work to be recorded; they never write membership, lifecycle, or gate state. Unrecorded answers (unfinished runs and transient failures) are cached per authority/run for 30 seconds with a single-flight guard so concurrent cold reads derive a run once. Their Carries lists and counts include bound projects; truly empty runs remain environment runs. Completion also compares this run's immutable `release_lineage` with the previous succeeded run for the same project and target environment. The resulting `carried_work` object keeps item matches under `items`, commits a release's own automation wrote under `release_output`, and commits made outside Yoke as SHAs under `commits`, subjects under `commit_subjects`, and authors under `commit_authors`, within each carried project. These commits never block creation, composition, start, or settlement; run pages, Shipping cards, Runs tables and release approvals offer an expandable "Also includes N commits made outside Yoke" list. **Item matches come only from records binding an exact commit to its item** — the item's merge receipt first, then QA and execution evidence and lane metadata; a commit message naming an item is never ownership evidence. A merge receipt records every commit its landing contributed (`contributed_commits`): the item's own first-parent line from the landed commit down to what the target already held, taken before the merge and, where the landing produced a merge commit, from that merge's other parent. A fast forward therefore credits each of the item's commits, and a branch sync's second-parent commits stay with whoever authored them. An item whose receipt predates that record, or whose landing left nothing to derive it from, may optionally tie its other commits to the item: `merge_receipt.commits.attest` (CLI: `yoke merge-receipt commits attest PREFIX-N --commit SHA [--commit SHA ...] --reason R`) records full SHAs on its newest landed receipt entry under `attested_commits`, beside the derived set, with the reason given. Recording it changes no lifecycle state; historical runs remain unset and recording is forward-only. The record is evidence, not membership — enrolling from it is a separate step, described under release admission below.

**A release writes commits as well as shipping them.** A promotion that rewrites a version pin pushes a real commit no backlog item authored, and it lands in the range the next release reads. The run that produced it records it — `deployment_runs.release_output.record` (CLI: `yoke deployment-runs release-output record RUN-ID --project P [--commit REF]`), stored per project inside that run's own `bound_sources` — and attribution reads that record instead of guessing from an author name or a file path. Item attribution is tried first and always wins; the record is consulted only for a commit no item claimed, and each `release_output` entry names the producing `run_id` and the recorded `reason`. So a range whose only unexplained commit is recorded release output composes with no `composition_resolution`, while a real-code commit nobody attributed refuses exactly as before.

The comparison runs wherever the completion does. A machine holding the
project's registered checkout reads git directly; anywhere else — including a
control plane serving an HTTPS-only project, which holds no checkout of it and
never will — the same comparison runs over the project's own authorized
repository binding. `derivation.source` names which answered (`checkout`,
`repository_provider`, or `none`).

**An empty release and an unanswerable comparison are different facts.**
`derivation.contents_known` is true when the answer is determinate: a comparison that ran, or a first run with no predecessor to compare against, which carries nothing and owes nothing — reporting that baseline as unknown would strand a project behind a blocker no repair could clear. `derivation.status` is derived from it: `derived` when commits were attributed, `empty` when the run genuinely carries nothing, and `unknown` when a comparison was owed and nobody could look. `derivation.reason` names the case and `derivation.recovery` names the
repair. Readers must not treat `unknown` as `empty`: an unknown record
suppresses both automatic enrollment and the omitted-delivery-ready-member scan
at composition freeze, because a set nobody computed can neither be admitted
nor cleared. Attribution is repaired, never guessed.

A record is written once and then frozen, which is right for a comparison that ran
and wrong for one that could not. `deployment_runs.carried_work.repair` (CLI: `yoke
deployment-runs carried-work repair RUN-ID`) replaces exactly that case: it refuses
a derived record, refuses a second unanswerable derivation, and names why the retry
still failed.

Completion gates ask whether the deployed candidate **contains** an item's recorded
merge, not whether it equals it — a batch has one tip, so equality could only ever
complete a single-item release. Two questions in order: ancestry, read from the
candidate's own side so a long history still costs one small page, then content, since
work that reached the base under other commit ids adds nothing while failing every
ancestry test (the merge boundary's own "this lane adds nothing", asked of the same
source). Both run against every source the host offers; an unreadable one names each.

Definition-schema-v2 runs freeze admission before execution. The candidate
`release_lineage` must be a full commit SHA; every nonterminal delivery-ready
change carried by that candidate must be a member, while done history,
merge-only flows, Task items, and Epic task graphs are not admitted implicitly.
The run records the shared artifact identity, an immutable composition digest,
the effective flow for every member, and full recoverable QA requirement/plan
content. Missing first-baseline attribution must be resolved explicitly before
start. Cancellation preserves the frozen evidence. Schema-v1 runs retain their
legacy start behavior.

**Composition completes candidate membership.** Run creation and item-bound composition (`deployment_runs.start_for_item`, `deployment_runs.validate_composition`) enroll every delivery-ready item the pinned candidate carries and the run does not hold, through the same admission validation `add_item` uses. Creation validates provisionally in its insertion transaction and rolls back on refusal; `deployment_runs.execution.context` revalidates before dispatch. Its driver reuses that context once; [start diagnostics](../deployment-start.md) explain containment-only refresh, batched reads, and flushed timing records.

Creation pins bound sources and checks every shipped project; start revalidates the same composition before dispatch. Independent admission, flow, and attribution blockers are returned together with their identities. A stored record missing a recorded bound project refuses with cancel-and-recreate recovery. That candidate set is two sources unioned before any lock is taken. The first is `carried_work` above — what this run adds over the run before it. The second (`deployment_run_unheld_candidates.unheld_candidate_ids`) exists because the first is a commit *range* and so has a floor at the previous succeeded release: a landing behind that floor is outside every later range permanently, so a cancelled or superseded run can leave members behind that floor; the second source recovers those unheld landings. The second source walks the run's carried projects for items that are merged, still open, delivery-ready under their pinned workflow, whose newest landing this run's own pinned lineage contains, and which no release holds; only definite containment enrolls; `not_contained` waits for a later candidate, while `undetermined` refuses with the item, reason, and recovery so unknown attribution cannot silently omit a member. **Custody there is asked of a landing, not of an item** (`delivery_landing_custody.landing_custody`): an item may land several times and those landings may straddle releases, so a run holds a landing only when the item is one of that run's members *and* the run's pinned lineage contains that landing's commit *and* the run is `created`, `executing`, or `succeeded`. Membership alone over-answers — a membership predating a newer merge is not custody of it — and containment alone over-answers in the other direction, since every release cut after a merge contains it including releases that never named the item. The four states are `held`, `remerged` (member runs exist, none carries this landing), `unheld`, and `undetermined`; the first and last enrol nothing. The landing's identity is `item_merge_identity` — the merge commit the item's newest receipt names — so custody compares the same identity the close-out gate does, while `merged_at` and `merge_queue_landed_at` decide only whether an item landed at all, never which landing. Enrollment takes the item workflow-binding locks and then the run row, the order `lock_run_with_stable_membership` and `add_item` already use, and locks every carried item rather than only the currently eligible ones, so eligibility cannot move between the decision and the insert; a run that is no longer `created` enrolls nothing. **Custody is resolved once, before any of those locks, and handed to every reader** (`deployment_run_unheld_candidates.resolve_candidate_custody`, returning a `CustodyResolution`): enrollment, the carried-membership refusal, the unclosable-final-member refusal and the skipped-candidate notice all need the same answer, so one resolution avoids repeated network containment reads while holding the run row lock. Because custody is asked with `exclude_run_id` set to this run, enrolling its own members cannot change the answer, so one resolution stays valid for the whole composition. A reader handed no resolution still walks for itself, and each keeps the behaviour it had on an undeterminable custody: enrollment raises it by name, the narrowing readers degrade to no exclusion. Composition freeze then verifies rather than completes: the driver read its members before reaching it and seeds QA and stamps release against that list, so a member arriving at freeze would execute unseeded, and freeze refuses by name instead. An item-less environment run on a v2 flow enrolls like any other, and deliberate member choices — an explicit `progress` intent included — are never rewritten. **Composition names what it skipped in one notice** (`deployment_run_skipped_candidates.skipped_candidate_notice`): carried items a live or succeeded release holds; carried items back in rework, whose status is before their workflow's release stage (under `release_stage` delivery a stage inside an implementation skill's segment is not delivery-ready unless it is the release wait itself, so a Dash sent back to `implementing` after a landing is never composed); members an operator removed; and dependents of a blocker that has not shipped — a blocker a live or settling release holds included, named with that run, since composition counts only a recorded `succeeded` delivery as shipped while completion authority reads a settling run as delivered. `yoke deployment-runs remove-item RUN-ID PREFIX-N --reason R` (`deployment_runs.remove_item`, deploy lock required, created runs or unsettled members at executing item QA or failed `item-qa-failed` without shared run QA/approval) deletes the membership row and records the reason, time, session and actor in `deployment_runs.membership_removals`; enrollment and the omitted-work refusal subtract it so composition never re-enrolls the item, its code still ships, and the next release's unheld-custody pass enrolls it. `add_item` clears the entry while created. A live item QA dispatch can already have loaded the removed member: if materialization or gating refuses, it skips that member only when the membership row is absent and the run records the removal, then continues the other members. A member missing without a recorded removal still fails loudly. A failed item-QA run remains failed after removal; resume it with `yoke watch deploy -- RUN-ID --from-stage item-qa`. Every other failed stage refuses removal. For red member QA, `yoke deployment-runs remove-item RUN ITEM --reason R` lets an independent run finish while the member waits for its next release; see `remove-item --help`. Settlement automatically releases members whose current candidate is outside the frozen lineage. A carried delivery-ready item with no resolvable completion flow refuses with the item and flow-selection command named; select a project workflow delivery default before retrying the start. Other refusals include a carried item whose project or stage this run cannot admit, an underivable carried set; refused creation rolls back the run, so there is no run to update. A commit no item owns ships freely with its SHA, subject and author recorded under its project, and a run whose members were inherited from a run that already froze them — a retry of the same candidate, marked by a member carrying a `requirement_snapshot` first — which reuses that immutable membership rather than deriving against a moved baseline.

Release wrap-up prints each member stamp and close-out step, then confirms the `succeeded` write; output before a slow operation does not assert completion. Composition warns for carried items merged into the candidate but not at release yet: wait for them or `add-item` once they reach release; it never auto-enrolls them early. Removal queues a holder notice saying outstanding run-bound QA was cancelled, not passed, and the item rides a later release: keep the claim, re-park, and do not attempt close-out because this run succeeds. Delivery-run cards show only QA bound to their own run; a run without item QA shows no item-QA count. Retracted requirements appear as cancelled with their removal reason and are excluded from pass counts, as are no-obligation records. Retracted run requirements are ignored by the done QA gate, while standing obligations and the item's delivery gate remain in force. Stage age reads only the durable `current_stage_entered_at` clock, including `complete`; repeated stage writes preserve it, older runs show unknown age, and snapshots without a source clock clear the prior stage's age when their stage changes.

## Table: deployment_stage_receipts

Durable executor observations for non-QA deployment-stage attempts. Events do
not substitute for this authority.

```sql
id INTEGER PRIMARY KEY
run_id TEXT NOT NULL REFERENCES deployment_runs(id)
stage_name TEXT NOT NULL
attempt_number INTEGER NOT NULL -- allocated before dispatch; increasing per run/stage
correlation_id TEXT NOT NULL -- idempotency key for one dispatch
target_kind TEXT NOT NULL -- persistent_environment | run_preview
target_name TEXT -- required when ready
status TEXT NOT NULL -- pending | ready | failed | cancelled
observed_url TEXT
observed_release_lineage TEXT -- required when ready; exact run candidate
observed_artifact_identity TEXT -- must match when the run pins an artifact
executor TEXT NOT NULL
executor_receipt TEXT
failure_reason TEXT -- required when failed or cancelled
created_at TEXT NOT NULL
completed_at TEXT -- required when ready
UNIQUE(run_id, stage_name, attempt_number)
UNIQUE(run_id, stage_name, correlation_id)
```

The attempt number, rather than row insertion order, determines the current
observation. A repeated correlation is accepted only with identical immutable
dispatch inputs, and a terminal callback cannot change its evidence. Scoped QA
consumes only the latest ready attempt from the QA target's earlier
`source_stage`, with the exact target and release lineage and, when the run pins
one, the exact artifact identity. A delayed older success cannot override a
newer failure, and a superseded receipt cannot revalidate an accepted execution
or later-stage prerequisite. Run-preview readiness requires an observed URL;
command-only persistent environments do not.

Who fills those observed columns is a per-target-kind decision,
registered in `deploy_pipeline_stage_receipt_producers.RECEIPT_PRODUCERS`.
Each producer takes one `ProducerContext` (the stage, its QA target, the
run and stage names, the project, the dispatch correlation id and the
dispatch callable) and returns a `StageObservation`: target name,
observed release lineage, optionally an observed URL and artifact identity. The
step runner's diagnostic travels to `executor_receipt` instead, so a producer
that reads a served URL and commit back reports them structurally rather than
encoding them in one string. An empty observed-identity column is not a gap to
fill with whatever string is at hand — the store compares observed against
pinned, so an invented value refuses the receipt, and a run pinning an artifact
identity no producer reads back is refused before the stage dispatches. The
registry's key set *is* the supported-target-kind list.

Release verification and notices — how release-to-done reads both QA
authorities, who observes a stage receipt, and the verdict and owner
notices — live in [release-delivery.md](release-delivery.md).

## Table: deployment_run_items

Membership table linking items to deployment runs. Zero rows for a run are valid when the run is an environment-level deploy with no attached backlog item; do not infer failure from item-less membership after the run has started executing.

```sql
run_id TEXT NOT NULL REFERENCES deployment_runs(id)
item_id INTEGER NOT NULL -- backlog item numeric ID
added_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
delivery_intent TEXT -- progress | final
requirement_selection TEXT -- member requirement/plan IDs; null until the freeze resolves a derived one
requirement_snapshot TEXT -- full selected requirement, plan, case, and attachment content
containment_attestation TEXT -- JSON: a lane checkout's containment verdict, recorded when this host could not answer
PRIMARY KEY (run_id, item_id)
```

Item-bound delivery starts from `/yoke usher PREFIX-N` or `yoke deployment-runs start-for-item`, which creates the run and inserts membership rows. `containment_attestation` is written later by the completion gate rather than by enrolment, and only where this host could not answer containment for itself — a lane checkout answered instead, and this is the evidence it relayed; the walk itself is in the delivery internals doc. For repeated continuous-slice delivery, intent is `progress` until the workflow's final predecessor and `final` at that final delivery posture. Member admission accepts explicit repeated `--requirement-id` and `--plan-id` selections and uses them verbatim. Where none is supplied — automatic enrollment, or `add-item` with no selection — it derives one from the item's outstanding post-deploy obligations: the unwaived, unsuperseded, run-unbound `qa_phase='post_deploy'` rows, plan-backed and ad-hoc alike, whose `target_env` a QA stage on the run's pinned flow targets (an undeclared `target_env` takes whichever target the stage observes). It derives nothing else: pre-merge `verification` rows are never rolled into a release. A post_deploy row is answered only by this run's admitted copy, so an empty selection would ship the code while leaving the item unable to reach `done`. A derived list has a shelf life, so admission validates one but does not store it: an obligation minted between that admission and the composition freeze belongs in it. The column stays null, which is what tells the freeze to derive again, and the freeze writes the list it resolves back concrete. An operator's stored selection is frozen exactly as given. Because a frozen row always carries a concrete list, a retry copies one and its own freeze takes it as given, so the candidate's acceptance contract travels with the candidate. An obligation no QA stage on the run targets is not a composition error — a stage run legitimately carries an item whose production acceptance belongs to the production run — but it is never silent: `validate_composition` and `add_item` name the row, its declared environment, and the stage targets the run does have. Membership is participation, not completion. Completion authority is a run of the item's selected (or project-default) completion flow, or another project's run that recorded a bound source commit for the item's project; `deployment_item_completion_runs.completion_runs` is the one walk the done gate's delivery fact, source QA, and the delivery ladder all read. Carried code, a failed run, or a same-project run of another flow closes nothing. The newest such membership is the one read, except that a failed or cancelled run — a duplicate cancelled before it executed, say — never shadows a live, settling, or succeeded one beside it. A final-delivery release — a flow that takes delivery custody, at the persistent tier — therefore refuses at `validate_composition` and at the executing freeze a same-project `final` member it could not close, naming the flow-selection and cancel recoveries; `progress` members, previews, and already-completed members are not refused. A custody-free run such as the stage half of a stage-then-production pair may still carry a member it does not close, and still enforces its own run-scoped QA and approvals; it cannot prove members at an item-scoped QA stage, which needs the member snapshots only a custody flow freezes, so creation, `add_item`, and `validate_composition` refuse such a run that carries or owes members by name (`item_qa_flow_without_delivery_custody`). A memberless item-scoped QA run is refused at `validate_composition` and the pre-execution check (`item_qa_run_without_members`) only when its flow is the completion flow for delivery-ready items no other release holds by landing custody (re-merged, unreadable, and supplemental-only holds stay owed); dispatch, the outstanding report, and the prior-stage acceptance check re-ask it and fail closed; a memberless run that owes no delivery, such as a stage run whose candidates were targeted out, passes the stage with the named `item_qa_no_member_owes_target` result. When a run with completion authority succeeds, automatic close-out stamps each cleared member's `delivery_evidence` rung before it reads that member's evidence. A run reads `succeeded` only after those close-outs happen (`deployment_run_collective_finalization`): it first records `settling_at` while still `executing`, completion authority reads a settling run as delivered, and each cleared member is then closed for real. Settlement has two phases. The commit phase first commits each cleared member's prerequisites, which close nothing and are idempotent: its `delivery_evidence` rung and its status preflight (materialized QA and any approval request), because the done gates read those on their own connections. It then writes every member's terminal status and claim release on the settlement's own connection — each member in its own savepoint, through the ordinary status write run inside the caller's transaction (`execute_update(..., conn=...)`), which then commits nothing itself — and commits once; any refusal rolls back the whole set, so none is closed and each keeps its claim and lane (`delivery_member_close_steps`). The refusal names blocked members with their own reason and the rest as held with the run. The effects phase runs after that commit over every member the run has closed: GitHub sync, terminal lane cleanup, and ending holder sessions left empty. Every effect is idempotent; a failure never reopens a closed member and keeps the run settling until a replay finishes the effects and the run is marked `succeeded`. Settlement also supersedes residue that recorded nothing: a live item-level (`item_id`) execution with `cursor_ordinal = 0` and no `qa_plan_execution_results` row, for a member whose run-scoped QA is satisfied, is aborted with `release_reason` `superseded-by-run-scoped-item-qa` (`qa_resultless_execution_supersession`); one with a result keeps refusing. Terminalizing a blocking execution replays the settling run (`settling_run_replay`), so clearing the blocker finishes the run without a hand re-drive; `yoke deployment-runs update RUN status succeeded` remains the explicit replay, and a member already done is not closed twice. Success also refuses while any non-`progress` member this run has completion authority for is still at its release wait, cleared or not, naming why (delivery not read as discharged, or post-deploy obligations unanswered). The delivery evidence ladder may credit a later successful release that contains the merge. Source post-deploy QA instead reads the newest eligible completion-flow membership: failed and cancelled attempts do not erase earlier accepted proof, an active newer member holds close-out, and a later containing release with no item membership supplies no admitted QA copy. An empty unresolved flow is merge-only — no completion run exists.

### The deploy lock gates create and execute

Creating a run (`deployment_runs.create`, `deployment_runs.start_for_item`) and executing one (`deployment-runs execute`, and the item form of the same pipeline) each refuse unless the calling session holds the project's deploy lock — the `deploy_serialization` coordination claim addressed by `DEPLOY:<project-slug>`. One driver owns a project's deployments, so a stage promotion cannot overtake the production promotion it precedes. Take it before the pair and release it after:

```text
yoke claims coordination-claim acquire --project P --key DEPLOY:P --reason "driving the release pair"
yoke claims coordination-claim release --project P --key DEPLOY:P --reason "release pair complete"
```

It is per project rather than per environment because a release pair deploys stage and production from one pinned source; both halves run under one hold, so no second driver slips between them. The steering seat takes it when it starts driving a pair and releases it when the pair completes. Refusals name the current holder, the acquire recipe, and the release recipe. `deployment_runs.create` also takes a caller `idempotency_key` (CLI `--idempotency-key`, required there) naming the one run the call intends. It is stored on that run as `deployment_runs.create_idempotency_key`, unique per project, with the canonical request in `create_request`, both written inside the table-locked creation transaction; a repeat with the same key and request returns the original run with `replayed: true` — even after the lock was released — and the same key with a changed input refuses `idempotency_key_conflict` naming the run and the differing fields. A create that yielded is usually still running: continue it; repeat with the same key only once it really exited without a run id. A deliberate second run of the same candidate takes a new key. Those two columns are additive, so they arrive with the serving build's boot converge — and a self-deploy creates its production run from a driver already at the new release against a database the old release still serves. Until they converge the key cannot be stored: the create proceeds without it, and under the same table lock a repeat returns the one never-started (`status='created'`) run carrying the identical resolved request. The receipt names which applies in `idempotency_basis` (`recorded_key` or `unconverged_request_match`, null when unkeyed); once a matched run has started, a repeat is a new run, and more than one never-started match refuses `idempotency_replay_ambiguous` naming them.

The kind is sticky: nothing reclaims the lock automatically, because a pipeline whose local driver died is still running on CI. After confirming the pipeline has settled, list the live claim and review its holder, then use the signed-in human action outside any harness session to free the exact stranded row with `yoke coordination-claim release --project P --key DEPLOY:P --claim-id N --holder-session-id S --reason "..."`. Manual and launched agent sessions are refused. This registered action works over HTTPS or local authority, requires project `claims.release` permission, refuses if the claim or holder changed after review, and records a WARN `OperatorLeaseRelease` plus the durable reason on the claim row.

Exclusivity is on `project_id` alone. The slug rides in the claim scope so the operator key renders without a database read, and renaming a project cannot hand out a second live lock.

A claim row is session-bound by foreign key, so there is no session-less deploy lock: a caller that resolves no harness session is refused and told the same recovery every claim-holding operation names — run it from a harness session, or, for an operator driving the deploy from a plain terminal, register one (`yoke sessions begin --help`) and point `$YOKE_SESSION_ID` at it so the acquire and the run share one holder.

Claim storage, stickiness, and the board rendering for every coordination kind: the "Shared-operation coordination claims" section of [`qa-and-sessions.md`](qa-and-sessions.md).

## Table: deployment_run_qa

Run-level QA requirements materialized at run creation.

```sql
run_id TEXT NOT NULL REFERENCES deployment_runs(id)
check_name TEXT NOT NULL -- e.g., 'smoke-test', 'manual-acceptance'
source TEXT NOT NULL -- 'flow-default', 'item-rollup', 'operator'
blocking INTEGER NOT NULL DEFAULT 1 -- 1 = blocks done transition
status TEXT NOT NULL DEFAULT 'pending' -- pending|passed|failed|waived
updated_at TEXT
PRIMARY KEY (run_id, check_name)
```

### Blocking QA holds the succeeded stamp

A run does not reach `status='succeeded'` while any blocking QA obligation is
unresolved. `deployment_runs.cmd_update` is the boundary that enforces it, so
every route into a succeeded stamp — the pipeline's own finalization included —
is covered by one check. Two tables carry those obligations, and both are read:

- `deployment_run_qa`, the flow-derived checks. Only `passed` and `waived`
  resolve one; `failed` does not, being the strongest reason not to call the
  run succeeded.
- `qa_requirements` rows keyed by `deployment_run_id`, the run's plan cases. One
  resolves on a `qa_runs` row with `verdict='pass'`, or on being settled without
  evidence — waived, or superseded by a replacement graded on its own evidence.
  That rule is shared with the stage acceptance check, so the end of a release
  never re-opens what a stage already accepted. A case whose latest run is
  `undetermined` and awaits human review is named with it and its authorities.
  The item `done` gate ignores a closed verdict-less item attempt only after its successor passes or is discharged (post-deploy proof needs accepted completion-member copies); an unsettled successor is named, and live runs and plans still block. It also reads the same rows when they name the item as
  `deployment_member_public_ref`; run-scoped rows with no member stay the run's.

Non-blocking checks never hold a run, and `force=True` overrides the
hold exactly as it overrides the stage checks beside it.

### The run-completing stage is held, not recorded early

The flow's last stage drawn green says the run delivered, so the
pipeline evaluates the run's blocking obligations *before* that stage
starts: with any unresolved it prints each one and exits 5 without
starting the stage, setting `current_stage`, emitting
`DeploymentRunStageStarted`, or allocating a receipt. That stage stays
pending on the card exactly while work remains, `status` stays
`executing`, and earlier stages keep their results. Settling the last
obligation advances accepted QA, approval, and auto stages under the
project deploy lock, then closes the run and eligible members. An attached
driver continues its own run; a failed close names recovery to its seat. A scoped-QA wait report also reads the stage's outstanding subjects through `deployment_qa_stage_outstanding`, the same reader as the fleet report: each waiting member counts once and its blockers are listed even without requirement rows or a completed scoped execution. The report includes unresolved run obligations too; only an empty combined report says nothing is outstanding. `deployment_runs.execution.qa_pending` accepts `stage_name` to return this `held_report` without changing its completion-only `unresolved` list. An older serving build missing that report refuses as `scoped_qa_report_unavailable`, prints the dispatch diagnostic, and names the control-plane upgrade recovery.

A blocking obligation bound to a run but naming no stage is refused at
admission wherever the flow pins QA stages: acceptance credits only rows
carrying its own stage name, so such a row would hold the run for
evidence that cannot arrive. Name the stage (and, on an item-scoped
stage, the member), or record it non-blocking. Owners:
`deployment_run_completion_preconditions`,
`deploy_pipeline_stage_checks`, `qa_deployment_run_stage_scope`.

## Table: deployment_preview_environments

Preview environment occupancy tracking for deployment runs.

```sql
id INTEGER PRIMARY KEY
project TEXT NOT NULL REFERENCES projects(id)
env_name TEXT NOT NULL -- e.g., 'stage', 'sandbox'
run_id TEXT REFERENCES deployment_runs(id)
status TEXT NOT NULL DEFAULT 'available' -- available | claimed | stale
url TEXT
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
env_type TEXT NOT NULL DEFAULT 'adhoc' -- shared | adhoc
UNIQUE(project, env_name)
```

## Table: ephemeral_environments

Tracks per-branch ephemeral environments for pre-merge E2E validation. GitHub Actions creates environments; Yoke tracks lifecycle via `python3 -m yoke_core.cli.db_router envs`.

```sql
id INTEGER PRIMARY KEY
project TEXT NOT NULL REFERENCES projects(id)
branch TEXT NOT NULL -- MUST use 'PREFIX-{id}' format (see Branch Naming Contract below)
item TEXT -- backlog item (e.g., 'PREFIX-N')
workflow_run_id TEXT -- GitHub Actions run ID that created this environment
github_ref TEXT -- git ref used for the environment
port_api INTEGER
port_web INTEGER
url TEXT
status TEXT NOT NULL DEFAULT 'pending' -- pending | starting | running | healthy | stopped | failed
started_at TEXT
stopped_at TEXT
health_check_url TEXT
deployed_sha TEXT -- commit SHA of last pushed code (enables push/poll short-circuit)
created_at TEXT
UNIQUE(project, branch)
```

### Branch Naming Contract

The `branch` column MUST use the value `PREFIX-{id}` (matching the item's worktree branch name, e.g., `PREFIX-N`). This convention is required for conduct compatibility -- the conduct skill queries ephemeral environments by `branch='PREFIX-{id}'` at steps d2, E1, and E3 in `dispatch-context.md`. CI systems that write ephemeral environment records (e.g., `external-webapp-ephemeral.yml`) must use the same `PREFIX-{id}` branch value. If a future project uses a different branch naming scheme, both the CI workflow and the conduct skill query must be updated in lockstep.
