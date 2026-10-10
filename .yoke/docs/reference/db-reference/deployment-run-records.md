# DB Reference — Deployment Run Records

Run, stage-attempt, membership, and QA authority. Read this before interpreting a release record or changing its membership. [DB reference](../db-reference.md) owns timestamp and JSON conventions; [events and environments](events-and-deployments.md) owns the event log and environment tracking.

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

**A release writes commits as well as shipping them.** A promotion that rewrites a version pin pushes a real commit no backlog item authored, and it lands in the range the next release reads. The run that produced it records it — `deployment_runs.release_output.record` (CLI: `yoke deployment-runs release-output record RUN-ID --project P [--commit REF]`), stored per project inside that run's own `bound_sources` — and attribution reads that record instead of guessing from an author name or a file path. Hosted bridge callers pass `--commit SHA --promotion-receipt-file PATH` with the exact successful attempt artifact; the server rechecks repository, run, environment, product, immutable digest and bound-candidate ancestry. Its `promotion_receipts` retain deployed identity even when no commit was produced; missing identity refuses hosted QA, while generic callers keep their existing output/binding behavior. Item attribution is tried first and always wins; the record is consulted only for a commit no item claimed, and each `release_output` entry names the producing `run_id` and the recorded `reason`. So a range whose only unexplained commit is recorded release output composes with no `composition_resolution`, while a real-code commit nobody attributed refuses exactly as before.

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

Creation pins bound sources and checks every shipped project; start revalidates the same composition before dispatch. Independent admission, flow, and attribution blockers are returned together with their identities. A stored record missing a recorded bound project refuses with cancel-and-recreate recovery. That candidate set is two sources unioned before any lock is taken. The first is `carried_work` above — what this run adds over the run before it. The second (`deployment_run_unheld_candidates.unheld_candidate_ids`) exists because the first is a commit *range* and so has a floor at the previous succeeded release: a landing behind that floor is outside every later range permanently, so a cancelled or superseded run can leave members behind that floor; the second source recovers those unheld landings. The second source walks the run's carried projects for items that are merged, still open, delivery-ready under their pinned workflow, whose newest landing this run's own pinned lineage contains, and which no release holds; only definite containment enrolls; `not_contained` waits for a later candidate, while `undetermined` refuses with the item, reason, and recovery so unknown attribution cannot silently omit a member. **Custody there is asked of a landing, not of an item** (`delivery_landing_custody.landing_custody`): an item may land several times and those landings may straddle releases, so a run holds a landing only when the item is one of that run's members *and* the run's pinned lineage contains that landing's commit *and* the run is `created`, `executing`, or `succeeded`. Membership alone over-answers — a membership predating a newer merge is not custody of it — and containment alone over-answers in the other direction, since every release cut after a merge contains it including releases that never named the item. The four states are `held`, `remerged` (member runs exist, none carries this landing), `unheld`, and `undetermined`; the first and last enrol nothing. The landing's identity is `item_merge_identity` — the merge commit the item's newest receipt names — so custody compares the same identity the close-out gate does, while `merged_at` and `merge_queue_landed_at` decide only whether an item landed at all, never which landing. Enrollment takes the item workflow-binding locks and then the run row, the order `lock_run_with_stable_membership` and `add_item` already use, and locks every carried item rather than only the currently eligible ones, so eligibility cannot move between the decision and the insert; a run that is no longer `created` enrolls nothing. **Custody is resolved once, before any of those locks, and handed to every reader** (`deployment_run_unheld_candidates.resolve_candidate_custody`, returning a `CustodyResolution`): enrollment, the carried-membership refusal, the unclosable-final-member refusal and the skipped-candidate notice all need the same answer, so one resolution avoids repeated network containment reads while holding the run row lock. Because custody is asked with `exclude_run_id` set to this run, enrolling its own members cannot change the answer, so one resolution stays valid for the whole composition. A reader handed no resolution still walks for itself, and each keeps the behaviour it had on an undeterminable custody: enrollment raises it by name, the narrowing readers degrade to no exclusion. Composition freeze then verifies rather than completes: the driver read its members before reaching it and seeds QA and stamps release against that list, so a member arriving at freeze would execute unseeded, and freeze refuses by name instead. An item-less environment run on a v2 flow enrolls like any other, and deliberate member choices — an explicit `progress` intent included — are never rewritten. **Composition names what it skipped in one notice** (`deployment_run_skipped_candidates.skipped_candidate_notice`): carried items a live or succeeded release holds; carried items back in rework, whose status is before their workflow's release stage (under `release_stage` delivery a stage inside an implementation skill's segment is not delivery-ready unless it is the release wait itself, so a Dash sent back to `implementing` after a landing is never composed); members an operator removed; and dependents of a blocker that has not shipped — a blocker a live or settling release holds included, named with that run, since composition counts only a recorded `succeeded` delivery as shipped while completion authority reads a settling run as delivered. `yoke deployment-runs remove-item RUN-ID PREFIX-N --reason R` (`deployment_runs.remove_item`, refused while another session is the run's live driver, created runs or unsettled members at executing item QA or failed `item-qa-failed` without shared run QA/approval) deletes the membership row and records the reason, time, session and actor in `deployment_runs.membership_removals`; enrollment and the omitted-work refusal subtract it so composition never re-enrolls the item, its code still ships, and the next release's unheld-custody pass enrolls it. `add_item` clears the entry while created. A live item QA dispatch can already have loaded the removed member: if materialization or gating refuses, it skips that member only when the membership row is absent and the run records the removal, then continues the other members. A member missing without a recorded removal still fails loudly. A failed item-QA run remains failed after removal; resume it with `yoke watch deploy -- RUN-ID --from-stage item-qa`. Every other failed stage refuses removal. For red member QA, `yoke deployment-runs remove-item RUN ITEM --reason R` lets an independent run finish while the member waits for its next release; see `remove-item --help`. Failed independent item QA automatically releases a member whose recorded merge is definitely outside its project's frozen lineage, using the same audited removal as settlement; unknown containment holds and reports recovery. Settlement also releases replaced candidates. A carried delivery-ready item with no resolvable completion flow refuses with the item and flow-selection command named; select a project workflow delivery default before retrying the start. Other refusals include a carried item whose project or stage this run cannot admit, an underivable carried set; refused creation rolls back the run, so there is no run to update. A commit no item owns ships freely with its SHA, subject and author recorded under its project, and a run whose members were inherited from a run that already froze them — a retry of the same candidate, marked by a member carrying a `requirement_snapshot` first — which reuses that immutable membership rather than deriving against a moved baseline.

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

Item-bound delivery starts from `/yoke usher PREFIX-N` or `yoke deployment-runs start-for-item`, which creates the run and inserts membership rows. `containment_attestation` is written later by the completion gate rather than by enrolment, and only where this host could not answer containment for itself — a lane checkout answered instead, and this is the evidence it relayed; the walk itself is in the delivery internals doc. For repeated continuous-slice delivery, intent is `progress` until the workflow's final predecessor and `final` at that final delivery posture. Member admission accepts explicit repeated `--requirement-id` and `--plan-id` selections and uses them verbatim. Where none is supplied — automatic enrollment, or `add-item` with no selection — it derives one from the item's outstanding post-deploy obligations: the unwaived, unsuperseded, run-unbound `qa_phase='post_deploy'` rows, plan-backed and ad-hoc alike, whose `target_env` a QA stage on the run's pinned flow targets (an undeclared `target_env` takes whichever target the stage observes). It derives nothing else: pre-merge `verification` rows are never rolled into a release. A post_deploy row is answered only by this run's admitted copy, so an empty selection would ship the code while leaving the item unable to reach `done`. A derived list has a shelf life, so admission validates one but does not store it: an obligation minted between that admission and the composition freeze belongs in it. The column stays null, which is what tells the freeze to derive again, and the freeze writes the list it resolves back concrete. An operator's stored selection is frozen exactly as given. Because a frozen row always carries a concrete list, a retry copies one and its own freeze takes it as given, so the candidate's acceptance contract travels with the candidate. An obligation no QA stage on the run targets is not a composition error — a stage run legitimately carries an item whose production acceptance belongs to the production run — but it is never silent: `validate_composition` and `add_item` name the row, its declared environment, and the stage targets the run does have. Membership is participation, not completion. A successful item `done` write atomically publishes `completed_deliveries` in its existing `delivery_evidence` stamp facts, naming the owner, member, run, registered environment, and exact candidate. Ordinary dependencies require `done`; environment-specific dependencies require both `done` and this durable attribution. Preflight stamps and accepted QA alone are not completion. Subsequent sibling failures or run cancellation cannot revoke a completed member, and supplemental successful environment deliveries append attribution for already-completed members. Dashboard and batched dependency readers consume this same fact. Completion authority is a run of the item's selected (or project-default) completion flow, or another project's run that recorded a bound source commit for the item's project; `deployment_item_completion_runs.completion_runs` is the one walk the done gate's delivery fact, source QA, and the delivery ladder all read. Carried code, a failed run, or a same-project run of another flow closes nothing. The newest such membership is the one read, except that a failed or cancelled run — a duplicate cancelled before it executed, say — never shadows a live, settling, or succeeded one beside it. A final-delivery release — a flow that takes delivery custody, at the persistent tier — therefore refuses at `validate_composition` and at the executing freeze a same-project `final` member it could not close, naming the flow-selection and cancel recoveries; `progress` members, previews, and already-completed members are not refused. A custody-free run such as the stage half of a stage-then-production pair may still carry a member it does not close, and still enforces its own run-scoped QA and approvals; it cannot prove members at an item-scoped QA stage, which needs the member snapshots only a custody flow freezes, so creation, `add_item`, and `validate_composition` refuse such a run that carries or owes members by name (`item_qa_flow_without_delivery_custody`). A memberless item-scoped QA run is refused at `validate_composition` and the pre-execution check (`item_qa_run_without_members`) only when its flow is the completion flow for delivery-ready items no other release holds by landing custody (re-merged, unreadable, and supplemental-only holds stay owed); dispatch, the outstanding report, and the prior-stage acceptance check re-ask it and fail closed; a memberless run that owes no delivery, such as a stage run whose candidates were targeted out, passes the stage with the named `item_qa_no_member_owes_target` result. When a run with completion authority succeeds, automatic close-out stamps each cleared member's `delivery_evidence` rung before it reads that member's evidence. A run reads `succeeded` only after those close-outs happen (`deployment_run_collective_finalization`): it first records `settling_at` while still `executing`, completion authority reads a settling run as delivered, and each cleared member is then closed for real. Settlement has two phases. The commit phase first commits each cleared member's prerequisites, which close nothing and are idempotent: its `delivery_evidence` rung and its status preflight (materialized QA and any approval request), because the done gates read those on their own connections. It then writes every member's terminal status and claim release on the settlement's own connection — each member in its own savepoint, through the ordinary status write run inside the caller's transaction (`execute_update(..., conn=...)`), which then commits nothing itself — and commits once; any refusal rolls back the whole set, so none is closed and each keeps its claim and lane (`delivery_member_close_steps`). The refusal names blocked members with their own reason and the rest as held with the run. The effects phase runs after that commit over every member the run has closed: GitHub sync, terminal lane cleanup, and ending holder sessions left empty. Every effect is idempotent; a failure never reopens a closed member and keeps the run settling until a replay finishes the effects and the run is marked `succeeded`. Settlement also supersedes residue that recorded nothing: a live item-level (`item_id`) execution with `cursor_ordinal = 0` and no `qa_plan_execution_results` row, for a member whose run-scoped QA is satisfied, is aborted with `release_reason` `superseded-by-run-scoped-item-qa` (`qa_resultless_execution_supersession`); one with a result keeps refusing. Terminalizing a blocking execution replays the settling run (`settling_run_replay`), so clearing the blocker finishes the run without a hand re-drive; `yoke deployment-runs update RUN status succeeded` remains the explicit replay, and a member already done is not closed twice. Success also refuses while any non-`progress` member this run has completion authority for is still at its release wait, cleared or not, naming why (delivery not read as discharged, or post-deploy obligations unanswered). The delivery evidence ladder may credit a later successful release that contains the merge. Source post-deploy QA instead reads the newest eligible completion-flow membership: failed and cancelled attempts do not erase earlier accepted proof, an active newer member holds close-out, and a later containing release with no item membership supplies no admitted QA copy. An empty unresolved flow is merge-only — no completion run exists.

### Target occupancy serializes deploys; no claim is taken

Creating a run (`deployment_runs.create`, `deployment_runs.start_for_item`) and executing one take no claim. Creation serializes against other creation under a transaction-scoped advisory lock, and what used to need a project-wide hold is answered by the run itself:

- **Occupancy.** A run occupies the origin (`scheme://host[:port]`, lowercased) of every environment it targets — the run's own target environment plus every environment a flow stage targets — from the moment it is marked `executing` until every QA stage of its flow has settled (`deployment_qa_stage_outstanding` reports nothing outstanding) or it is terminal. A run whose flow has no QA stage holds its origins until it is terminal. The start (`status -> executing`) takes a transaction-scoped advisory lock per origin and refuses with `target_occupied` when another executing run still holds one, naming the origin, the holding run, its project and stage, and its open QA lines, with the recovery: re-run the start once the holder's QA settles, or terminalize a holder nobody will finish (`yoke deployment-runs terminalize RUN --disposition cancelled --reason R`). Environment records that resolve to one origin — two projects' stage environments on one host — are one occupancy unit with no configuration, and production origins are occupied exactly like stage ones, which keeps a later release from overtaking an earlier one on the same server. A run with no registered environment url (a frozen preview, which occupies its own slug instead) holds no origin. Owner: `deploy_target_occupancy`.
- **Who drives.** A run's live driver attachment (`deployment_runs.driver_attachment`, heartbeat within ten minutes) is the session driving it. Execution, membership and containment calls from any other session refuse with `run_driven_elsewhere` naming that driver; a run with no live driver may be driven by any authorized session, and a driver whose heartbeat lapses frees the run by itself — nothing needs a human release. Run-scoped notices, prepared-run hand-offs, automatic completion and operator QA-waiver authority read the same attachment and fall back to the project's steering seat.
- **Identity at QA start.** `qa.plan_execution.begin` for a deployment stage returns `deployment_start_identity`: the stage's persistent target, its served-revision path, and the commit the run delivered for that project. Before any host reset or human gate the runner asks the target what it serves; a different build refuses with `deployment_target_drifted`, aborts the begun execution and names both builds. A target that cannot be asked is reported as unverified and the per-case checks still apply.

Live `deploy_serialization` claims from the retired per-project lock were released by history entry `0070_release_retired_deploy_locks`, which also dropped their exclusivity index; the released rows remain as claim history, and a `DEPLOY:` key now refuses with `deploy_lock_retired`.

`deployment_runs.create` also takes a caller `idempotency_key` (CLI `--idempotency-key`, required there) naming the one run the call intends. It is stored on that run as `deployment_runs.create_idempotency_key`, unique per project, with the canonical request in `create_request`, both written inside the table-locked creation transaction; a repeat with the same key and request returns the original run with `replayed: true` — even after the lock was released — and the same key with a changed input refuses `idempotency_key_conflict` naming the run and the differing fields. A create that yielded is usually still running: continue it; repeat with the same key only once it really exited without a run id. A deliberate second run of the same candidate takes a new key. Those two columns are additive, so they arrive with the serving build's boot converge — and a self-deploy creates its production run from a driver already at the new release against a database the old release still serves. Until they converge the key cannot be stored: the create proceeds without it, and under the same table lock a repeat returns the one never-started (`status='created'`) run carrying the identical resolved request. The receipt names which applies in `idempotency_basis` (`recorded_key` or `unconverged_request_match`, null when unkeyed); once a matched run has started, a repeat is a new run, and more than one never-started match refuses `idempotency_replay_ambiguous` naming them.

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
  The item `done` gate uses each requirement's newest execution for settlement and code identity; older attempts never block. Browser reviews use the capture's verdict and identity, excluding detached agent verdict rows. A latest closed, verdict-less execution on a superseded requirement stops blocking only after its successor passes or is discharged (post-deploy proof needs accepted completion-member copies). Refusals name unsettled successors; latest live executions and active plans still block. The gate also reads the same rows when they name the item as
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
obligation advances accepted QA, approval, and auto stages on the serving
control plane, then closes the run and eligible members. An attached
driver continues its own run; a failed close names recovery to its seat. A scoped-QA wait report also reads the stage's outstanding subjects through `deployment_qa_stage_outstanding`, the same reader as the fleet report: each waiting member counts once and its blockers are listed even without requirement rows or a completed scoped execution. The report includes unresolved run obligations too; only an empty combined report says nothing is outstanding. `deployment_runs.execution.qa_pending` accepts `stage_name` to return this `held_report` without changing its completion-only `unresolved` list. An older serving build missing that report refuses as `scoped_qa_report_unavailable`, prints the dispatch diagnostic, and names the control-plane upgrade recovery.

A blocking obligation bound to a run but naming no stage is refused at
admission wherever the flow pins QA stages: acceptance credits only rows
carrying its own stage name, so such a row would hold the run for
evidence that cannot arrive. Name the stage (and, on an item-scoped
stage, the member), or record it non-blocking. Owners:
`deployment_run_completion_preconditions`,
`deploy_pipeline_stage_checks`, `qa_deployment_run_stage_scope`.
