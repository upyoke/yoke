# Deployment run members and QA

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Deployments](../index.md) > Run members and QA
<!-- /yoke:breadcrumbs -->

Read the member record, target occupancy, run drivers and run-bound QA. Plan ownership is frozen per member ([QA dispatch](../qa-dispatch.md#frozen-member-plans)).
## Member reads and completion diagnostics

`yoke deployment-runs get RUN member_items membership_removals` lists attached
members and each audited removal (`reason`, `removed_at`, `later_run_id`).
`carried_work` is recorded at freeze; until then get derives it live, unrecorded.

`yoke deployment-runs get RUN --include-member-closure` explicitly requests
`member_closure` beside the run fields. Ordinary full and field reads skip this
expensive diagnostic, so driver pinning reads only `project` and
`release_lineage`. During settlement the diagnostic reads current canonical
member prerequisites, requirement
ids, phases and declared targets, independently blocked members, atomic siblings,
and other-target deferrals. Its `blocked` flag describes member settlement,
not the count of run-bound QA. An empty run-bound case set proves nothing about
item completion. Closed members may still have finalization effects pending.

Satisfy each named requirement or gate through its registered recovery. A live
driver retains execution authority; do not dispatch another one. Repeating a
success write cannot supply missing acceptance. These diagnostics never run
close-out or change QA history, acceptance, lifecycle, or atomicity.

## Table: deployment_run_items

Membership table linking items to deployment runs. Zero rows for a run are valid when the run is an environment-level deploy with no attached backlog item; do not infer failure from item-less membership after the run has started executing.

```sql
run_id TEXT NOT NULL REFERENCES deployment_runs(id)
item_id INTEGER NOT NULL -- backlog item numeric ID
added_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" in Related
delivery_intent TEXT -- progress | final
requirement_selection TEXT -- member requirement/plan IDs; null until the freeze resolves a derived one
requirement_snapshot TEXT -- full selected item-case requirement content; post-deploy plans are never saved
containment_attestation TEXT -- JSON: a lane checkout's containment verdict, recorded when this host could not answer
PRIMARY KEY (run_id, item_id)
```

Item-bound delivery starts from `/yoke usher PREFIX-N` or `yoke deployment-runs start-for-item`, which creates the run, takes over a waiting run on its target, inserts the item's membership row and validates composition in one transaction; a refusal at any step writes nothing, and an item the takeover moved is not enrolled twice. `containment_attestation` is written later by the completion gate rather than by enrolment, and only where this host could not answer containment for itself — a lane checkout answered instead, and this is the evidence it relayed; the walk itself is in the delivery internals doc. Continuous slices use `progress` until final delivery, then `final`. Member admission accepts explicit repeated `--requirement-id` and `--plan-id` selections and uses them verbatim. Where none is supplied — automatic enrollment, or `add-item` with no selection — it derives one from the item's outstanding post-deploy obligations: the unwaived, unsuperseded, run-unbound `qa_phase='post_deploy'` item-case rows with no plan_id whose `target_env` a QA stage on the run's pinned flow targets (an undeclared `target_env` takes whichever target the stage observes). Item QA entry fixes plan ownership: one attacher runs member QA; shared plans form driver-owned groups; retained per-item plan copies count in no gate or answer. It derives nothing else: pre-merge `verification` rows are never rolled into a release. A post_deploy row is answered only by this run's admitted copy, so an empty selection would ship the code while leaving the item unable to reach `done`. Admission validates but does not store a derived list: null tells the freeze to derive again, including intervening obligations, and persist the result. Explicit selections freeze verbatim; retries preserve that frozen acceptance contract. An obligation no QA stage on the run targets is not a composition error — a stage run legitimately carries an item whose production acceptance belongs to the production run — but it is never silent: `validate_composition` and `add_item` name the row, its declared environment, and the stage targets the run does have. Membership is participation, not completion: which run may close a member, and how a run settles its members, is in [settlement](../settlement.md).

### Target occupancy serializes deploys; no claim is taken

Failed runs retain open QA and live executions, including red and timing
cases, for retry or same-flow, same-target takeover. Failure releases target
occupancy. Cancellation still aborts live executions and retracts unsettled
requirements; cooperative aborts keep custody until cleanup. Passing proof,
standing plans and review bundles remain. Verdict writes link execution and
artifacts, then re-evaluate stage acceptance. Cancelled runs cannot restart.

Predecessor removals record transferred members with `transferred_to_run_id`.
They keep admission and QA during rework; only new members need readiness.
At execution context and resume, open landings or implementing/reviewing members
are set aside, preserving unfinished QA and executions for the next enrolling
run on that flow and target. Remaining members keep frozen source containment.

Creating a run (`deployment_runs.create`, `deployment_runs.start_for_item`) and executing one take no claim. Creation serializes against other creation for the same project under a transaction-scoped advisory lock that covers only the database re-check and insert (composition's repository reads finish before it is taken), and what used to need a project-wide hold is answered by the run itself:

- **Occupancy.** A run occupies the origin (`scheme://host[:port]`, lowercased) of every environment it targets — the run's own target environment plus every environment a flow stage targets — from the moment it is marked `executing` until its cursor has reached its flow's QA stages and every one has settled (`deployment_qa_stage_outstanding` reports nothing outstanding) or it is terminal. A run whose cursor is still on a stage before its first QA stage is deploying and holds its origins with the open line `deploying: stage <name>`, whatever its QA will owe, so a memberless run whose QA owes nothing still holds them until its deploy stages are done. A run whose flow has no QA stage holds its origins until it is terminal. The start (`status -> executing`) takes a transaction-scoped advisory lock per origin and refuses with `target_occupied` when another executing run still holds one, naming the origin, the holding run, its project and stage, and its open QA lines, with the recovery: re-run the start once the holder finishes deploying and its QA settles, or terminalize a holder nobody will finish (`yoke deployment-runs terminalize RUN --disposition cancelled --reason R`). Environment records that resolve to one origin — two projects' stage environments on one host — are one occupancy unit with no configuration, and production origins are occupied exactly like stage ones, which keeps a later release from overtaking an earlier one on the same server. A run with no registered environment url (a frozen preview, which occupies its own slug instead) holds no origin. Owner: `deploy_target_occupancy`.
- **Takeover.** A newer release on the same flow and target can take over a run waiting on QA, moving its unfinished members and QA intact. See [takeover](../takeover.md).
- **Who drives.** A run's live driver attachment (`deployment_runs.driver_attachment`, heartbeat within ten minutes) is the session driving it. Execution, membership and containment calls from any other session refuse with `run_driven_elsewhere` naming that driver; a run with no live driver may be driven by any authorized session, and a driver whose heartbeat lapses frees the run by itself — nothing needs a human release. Run-scoped notices, prepared-run hand-offs, automatic completion and operator QA-waiver authority read the same attachment and fall back to the project's steering seat.
- **Identity at QA start.** `qa.plan_execution.begin` for a deployment stage returns `deployment_start_identity`: the stage's persistent target, its served-revision path, and the commit the run delivered for that project. Before any host reset or human gate the runner asks the target what it serves. QA tests whatever is deployed, so a different build (for example a newer release that took over) is reported on stderr with both commits named and QA proceeds; a target that cannot be asked is reported as unverified. Each case records the commit it observed.

Nothing takes a `deploy_serialization` claim any more: a `DEPLOY:` key refuses with `deploy_lock_retired`. A hold taken before the retirement still lists under its `DEPLOY:<project>` key until its holder releases it by id (`yoke claims coordination-claim release --claim-id N --reason R`); the kind is no longer sticky, so the session sweep frees one whose holder ended. Released rows remain as claim history.

Creation is idempotent per `--idempotency-key`; see [cutting runs](../cutting-runs.md#idempotent-creation).

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

Before interpreting or advancing a run to its terminal stage, read
[Blocking QA holds the succeeded stamp](../../verification/platform.md#blocking-qa-holds-the-succeeded-stamp).

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
driver continues its own run; a failed close names recovery to its seat. A scoped-QA wait report also reads the stage's outstanding subjects through `deployment_qa_stage_outstanding`, the same reader as the fleet report: each waiting member counts once and its blockers are listed even without requirement rows or a completed scoped execution. The report includes unresolved run obligations too; only an empty combined report says nothing is outstanding. `deployment_runs.execution.qa_pending` accepts `stage_name` to return this `held_report` without changing its completion-only `unresolved` list. An older serving build missing that report refuses as `scoped_qa_report_unavailable`, prints the dispatch diagnostic, and names the control-plane upgrade recovery. The read answers its whole run in a fixed number of statements, whatever the member count. The driver re-reads a read-only execution call that answers `read_deadline_exceeded` after a short bounded backoff; when every attempt expires, the blocking-QA check prints `could not evaluate blocking QA` with the rerun recovery and exits as a stage failure rather than a usage error.

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
