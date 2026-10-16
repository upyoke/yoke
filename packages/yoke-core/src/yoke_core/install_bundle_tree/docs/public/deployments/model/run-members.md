# Deployment run members and QA

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Deployments](../index.md) > Run members and QA
<!-- /yoke:breadcrumbs -->

Read deployment membership, target occupancy and run-bound QA authority before changing a release membership.

## Table: deployment_run_items

Membership table linking items to deployment runs. Zero rows for a run are valid when the run is an environment-level deploy with no attached backlog item; do not infer failure from item-less membership after the run has started executing.

```sql
run_id TEXT NOT NULL REFERENCES deployment_runs(id)
item_id INTEGER NOT NULL -- backlog item numeric ID
added_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" in Related
delivery_intent TEXT -- progress | final
requirement_selection TEXT -- member requirement/plan IDs; null until the freeze resolves a derived one
requirement_snapshot TEXT -- full selected requirement, plan, case, and attachment content
containment_attestation TEXT -- JSON: a lane checkout's containment verdict, recorded when this host could not answer
PRIMARY KEY (run_id, item_id)
```

Item-bound delivery starts from `/yoke usher PREFIX-N` or `yoke deployment-runs start-for-item`, which creates the run and inserts membership rows. `containment_attestation` is written later by the completion gate rather than by enrolment, and only where this host could not answer containment for itself — a lane checkout answered instead, and this is the evidence it relayed; the walk itself is in the delivery internals doc. For repeated continuous-slice delivery, intent is `progress` until the workflow's final predecessor and `final` at that final delivery posture. Member admission accepts explicit repeated `--requirement-id` and `--plan-id` selections and uses them verbatim. Where none is supplied — automatic enrollment, or `add-item` with no selection — it derives one from the item's outstanding post-deploy obligations: the unwaived, unsuperseded, run-unbound `qa_phase='post_deploy'` rows, plan-backed and ad-hoc alike, whose `target_env` a QA stage on the run's pinned flow targets (an undeclared `target_env` takes whichever target the stage observes). It derives nothing else: pre-merge `verification` rows are never rolled into a release. A post_deploy row is answered only by this run's admitted copy, so an empty selection would ship the code while leaving the item unable to reach `done`. A derived list has a shelf life, so admission validates one but does not store it: an obligation minted between that admission and the composition freeze belongs in it. The column stays null, which is what tells the freeze to derive again, and the freeze writes the list it resolves back concrete. An operator's stored selection is frozen exactly as given. Because a frozen row always carries a concrete list, a retry copies one and its own freeze takes it as given, so the candidate's acceptance contract travels with the candidate. An obligation no QA stage on the run targets is not a composition error — a stage run legitimately carries an item whose production acceptance belongs to the production run — but it is never silent: `validate_composition` and `add_item` name the row, its declared environment, and the stage targets the run does have. Membership is participation, not completion. A successful item `done` write atomically publishes `completed_deliveries` in its existing `delivery_evidence` stamp facts, naming the owner, member, run, registered environment, and exact candidate. Ordinary dependencies require `done`; environment-specific dependencies require both `done` and this durable attribution. Preflight stamps and accepted QA alone are not completion. Subsequent sibling failures or run cancellation cannot revoke a completed member, and supplemental successful environment deliveries append attribution for already-completed members. Dashboard and batched dependency readers consume this same fact. Completion authority is a run of the item's selected (or project-default) completion flow, or another project's run that recorded a bound source commit for the item's project; `deployment_item_completion_runs.completion_runs` is the one walk the done gate's delivery fact, source QA, and the delivery ladder all read. Carried code, a failed run, or a same-project run of another flow closes nothing. The newest such membership is the one read, except that a failed or cancelled run — a duplicate cancelled before it executed, say — never shadows a live, settling, or succeeded one beside it. A final-delivery release — a flow that takes delivery custody, at the persistent tier — therefore refuses at `validate_composition` and at the executing freeze a same-project `final` member it could not close, naming the flow-selection and cancel recoveries; `progress` members, previews, and already-completed members are not refused. A custody-free run such as the stage half of a stage-then-production pair may still carry a member it does not close, and still enforces its own run-scoped QA and approvals; it cannot prove members at an item-scoped QA stage, which needs the member snapshots only a custody flow freezes, so creation, `add_item`, and `validate_composition` refuse such a run that carries or owes members by name (`item_qa_flow_without_delivery_custody`). A memberless item-scoped QA run is refused at `validate_composition` and the pre-execution check (`item_qa_run_without_members`) only when its flow is the completion flow for delivery-ready items no other release holds by landing custody (re-merged, unreadable, and supplemental-only holds stay owed); dispatch, the outstanding report, and the prior-stage acceptance check re-ask it and fail closed; a memberless run that owes no delivery, such as a stage run whose candidates were targeted out, passes the stage with the named `item_qa_no_member_owes_target` result. When a run with completion authority succeeds, automatic close-out stamps each cleared member's `delivery_evidence` rung before it reads that member's evidence. A run reads `succeeded` only after those close-outs happen (`deployment_run_collective_finalization`): it first records `settling_at` while still `executing`, completion authority reads a settling run as delivered, and each cleared member is then closed for real. Settlement has two phases. The commit phase first commits each cleared member's prerequisites, which close nothing and are idempotent: its `delivery_evidence` rung and its status preflight (materialized QA and any approval request), because the done gates read those on their own connections. It then writes every member's terminal status and claim release on the settlement's own connection — each member in its own savepoint, through the ordinary status write run inside the caller's transaction (`execute_update(..., conn=...)`), which then commits nothing itself — and commits once; any refusal rolls back the whole set, so none is closed and each keeps its claim and lane (`delivery_member_close_steps`). Before writing any member it compares the required members with the cleared and prepared ones; a required member not cleared, or any prepare refusal, refuses at once without staging a status write. The refusal leads with the error code `run_settlement_blocked`, which both `deployment_runs.update` and `deployment_runs.execution.update` return, and names blocked members with their own reason and the rest as held with the run. The effects phase runs after that commit over every member the run has closed: GitHub sync, terminal lane cleanup, and ending holder sessions left empty (`delivery_member_close_effects`). No transaction stays open across that file-system and network work, which can take minutes per member: the phase ends its member read's transaction first, and each member's database steps commit on their own short connection, reopened once if it drops, so the server never ends an idle-in-transaction session under the run and a lost connection costs only the member whose step it carried. Every effect is idempotent; a failure never reopens a closed member and keeps the run settling until a replay finishes the effects and the run is marked `succeeded`. Settlement also supersedes residue that recorded nothing: a live item-level (`item_id`) execution with `cursor_ordinal = 0` and no `qa_plan_execution_results` row, for a member whose run-scoped QA is satisfied, is aborted with `release_reason` `superseded-by-run-scoped-item-qa` (`qa_resultless_execution_supersession`); one with a result keeps refusing. Terminalizing a blocking execution replays the settling run (`settling_run_replay`), so clearing the blocker finishes the run without a hand re-drive; `yoke deployment-runs update RUN status succeeded` remains the explicit replay, and a member already done is not closed twice. Success also refuses while any non-`progress` member this run has completion authority for is still at its release wait, cleared or not, naming why (delivery not read as discharged, a blocking done-gate QA requirement still open — each named with its recovery — or post-deploy obligations unanswered). The delivery evidence ladder may credit a later successful release that contains the merge. Source post-deploy QA instead reads the newest eligible completion-flow membership: failed and cancelled attempts do not erase earlier accepted proof, an active newer member holds close-out, and a later containing release with no item membership supplies no admitted QA copy. A supplemental membership — a run on another persistent environment, such as stage beside a production final run — answers an environment-targeted source only when it recorded the current final run's pinned or delivered item-project commit (`delivered_source_sha`, which reads a hosted promotion's receipt); holder coverage applies the same rule, and `add-item` warns `supplemental_proof_not_credited` when neither matches. An empty unresolved flow is merge-only — no completion run exists.

### Target occupancy serializes deploys; no claim is taken

Failure or cancellation aborts every live QA execution on that run and retracts
its unsettled run requirements in the status transaction. Passing proof and
standing plans remain. Completed captures retain typed review bundles for an
independent verdict; review never reopens the failed run. Deployment verdict
writes link the actual execution and artifacts automatically, then re-evaluate
active stage acceptance after commit, even when no driver is attached. Retrying
a failed run restores its automatic retractions; manual retractions stay retired
and the aborted execution stays terminal. Cancelled runs cannot restart.

Creating a run (`deployment_runs.create`, `deployment_runs.start_for_item`) and executing one take no claim. Creation serializes against other creation under a transaction-scoped advisory lock that covers only the database re-check and insert (composition's repository reads finish before it is taken), and what used to need a project-wide hold is answered by the run itself:

- **Occupancy.** A run occupies the origin (`scheme://host[:port]`, lowercased) of every environment it targets — the run's own target environment plus every environment a flow stage targets — from the moment it is marked `executing` until every QA stage of its flow has settled (`deployment_qa_stage_outstanding` reports nothing outstanding) or it is terminal. A run whose flow has no QA stage holds its origins until it is terminal. The start (`status -> executing`) takes a transaction-scoped advisory lock per origin and refuses with `target_occupied` when another executing run still holds one, naming the origin, the holding run, its project and stage, and its open QA lines, with the recovery: re-run the start once the holder's QA settles, or terminalize a holder nobody will finish (`yoke deployment-runs terminalize RUN --disposition cancelled --reason R`). Environment records that resolve to one origin — two projects' stage environments on one host — are one occupancy unit with no configuration, and production origins are occupied exactly like stage ones, which keeps a later release from overtaking an earlier one on the same server. A run with no registered environment url (a frozen preview, which occupies its own slug instead) holds no origin. Owner: `deploy_target_occupancy`.
- **Takeover.** Creating a run for the flow and target of an executing run that waits only on item QA (deploy stages done, cursor on an item-scoped QA stage, only QA or approval stages left, QA still open) takes that run over in the creation transaction, when the new pinned candidate contains the older run's `release_lineage`. Without run-level QA or approval, members whose every item-scoped QA stage accepted them stay; every other unclosed member is removed with the audited member removal (`membership_removals`, reason naming the new run) and admitted to the new run. With run-level QA or approval, every unclosed member moves and the older run is terminalized `cancelled`, which retracts its unpassed run-bound requirements. An older run left with no members is cancelled the same way; one that kept passed members has its open memberless requirements retracted and completes through its ordinary close-out. The new run records `supersedes_run_id` and the older one `superseded_by_run_id`. Refusals: `takeover_candidate_not_contained` (lists the members to release by hand) and `takeover_run_driven_elsewhere`. Owner: `deployment_run_target_takeover`.
- **Who drives.** A run's live driver attachment (`deployment_runs.driver_attachment`, heartbeat within ten minutes) is the session driving it. Execution, membership and containment calls from any other session refuse with `run_driven_elsewhere` naming that driver; a run with no live driver may be driven by any authorized session, and a driver whose heartbeat lapses frees the run by itself — nothing needs a human release. Run-scoped notices, prepared-run hand-offs, automatic completion and operator QA-waiver authority read the same attachment and fall back to the project's steering seat.
- **Identity at QA start.** `qa.plan_execution.begin` for a deployment stage returns `deployment_start_identity`: the stage's persistent target, its served-revision path, and the commit the run delivered for that project. Before any host reset or human gate the runner asks the target what it serves; a different build refuses with `deployment_target_drifted`, aborts the begun execution and names both builds. A target that cannot be asked is reported as unverified and the per-case checks still apply.

Nothing takes a `deploy_serialization` claim any more: a `DEPLOY:` key refuses with `deploy_lock_retired`. A hold taken before the retirement still lists under its `DEPLOY:<project>` key until its holder releases it by id (`yoke claims coordination-claim release --claim-id N --reason R`); the kind is no longer sticky, so the session sweep frees one whose holder ended. Released rows remain as claim history.

`deployment_runs.create` also takes a caller `idempotency_key` (CLI `--idempotency-key`, required there) naming the one run the call intends. It is stored on that run as `deployment_runs.create_idempotency_key`, unique per project, with the canonical request in `create_request`, both written inside the table-locked creation transaction; a repeat with the same key and request returns the original run with `replayed: true` — even after the lock was released — and the same key with a changed input refuses `idempotency_key_conflict` naming the run and the differing fields. A create that yielded is usually still running: continue it; repeat with the same key only once it really exited without a run id. A deliberate second run of the same candidate takes a new key. Those two columns are additive, so they arrive with the serving build's boot converge — and a self-deploy creates its production run from a driver already at the new release against a database the old release still serves. Until they converge the key cannot be stored: the create proceeds without it, and under the same table lock a repeat returns the one never-started (`status='created'`) run carrying the identical resolved request. The receipt names which applies in `idempotency_basis` (`recorded_key` or `unconverged_request_match`, null when unkeyed); once a matched run has started, a repeat is a new run, and more than one never-started match refuses `idempotency_replay_ambiguous` naming them.

Claim storage, stickiness, and the board rendering for every coordination kind: [Shared-operation coordination claims](../../sessions/model/coordination.md#shared-operation-coordination-claims).

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

## Related

- [Runs](runs.md)
- [Stage receipts](stage-receipts.md)
- [Timestamp discipline](../../databases/migrations.md#timestamp-discipline)
