# Deployment runs and packaged capabilities

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Delivery
<!-- /yoke:breadcrumbs -->

The rules file every session loads carries the short normative form of each rule. This document is the deep home the rules file points at: the same rules with the reasoning, the worked failure modes, the flag matrices, and the edge cases that decide close calls. Read the section you need before the action it governs — nothing here is optional background, it is simply longer than a startup channel can carry.

## Deployment runs

- **Runs occupy servers, not projects; flow id != run id.** No claim is taken to create or execute a run. A run occupies the origin (`scheme://host[:port]`) of every environment it targets from the moment it starts executing until its QA stages settle or it is terminal; a second run that would deploy to an occupied origin refuses at start with `target_occupied`, naming the holding run, its open QA lines and the recovery. Environment records in different projects that name one host are one occupancy unit, and production origins are occupied like stage ones, so a later release cannot overtake an earlier one on the same server. A run with a live driver attachment answers only to that driver's session (`run_driven_elsewhere`); a driver whose heartbeat lapses frees the run by itself. Before a deployment QA stage resets a host or raises a human gate, the runner asks the frozen target what it serves and refuses drift (`deployment_target_drifted`) naming both builds. A hosted flow definition id is not a run id; run ids look like `run-YYYYMMDD-NNN`, and `/yoke usher PREFIX-N` creates runs through `yoke deployment-runs start-for-item`, writes `deployment_run_items`, executes the pipeline, then moves members to `done`.
- **A newer run takes over a run waiting only on item QA.** `yoke deployment-runs create` for the flow and target of an executing run whose deploy stages are done and whose cursor stands on item QA (only QA/approval gates and the declared final `auto` completion remain) takes that run over in the creation transaction, so slow item QA never blocks a newer candidate. With no run-level QA or approval in the flow, members whose item QA passed stay and close normally there, and each waiting member is removed through the audited `remove-item` path and enrolled in the new run. With run-level QA or approval, the shared gates hold every member, so every unclosed member moves and the older run is cancelled as superseded with nothing recorded as passed; the new run seeds its run-level QA from the flow definition, keeping gate order. Open memberless shared-plan copies and run-level requirements without a pass are retracted on the older run, and the new run materializes its own. `supersedes_run_id` on the new run and `superseded_by_run_id` on the older one record it, and the create receipt names `supersedes_run_id`. The takeover refuses with `takeover_candidate_not_contained`, listing the members to release by hand, unless the new candidate contains the older one; it refuses with `takeover_run_driven_elsewhere` while another session's live driver holds the older run. A run created without a pinned commit, or on a database whose supersession columns have not converged, takes nothing over, and its start meets the older run's `target_occupied` refusal.
- **Disable definitions; retain history.** `yoke deployment-flows set-status <flow-id> disabled` prevents new assignments and runs without deleting the definition or any historical run. A definition referenced by a run is immutable and cannot be deleted; change it with `yoke deployment-flows version` (records `supersedes_flow_id`) and disable the predecessor. Items pinned to a retired flow follow its newest active same-project successor with the same target environment and tier for admission, completion, and `start-for-item`; a delivery already made on the retired flow still closes them. The stored pin stays, reported as `pinned`, and needs no rebind.
- **Schema/env shape:** `deployment_runs` has no `item_id`; `deployment_run_items` may be empty for started environment runs. The HTTPS product/API environment is the normal relayed authority, and it drives ordinary delivery end to end — create, start-for-item, execute, watch, retry, close-out — over whichever connection holds the run row. A serving-API self-deploy requires control-plane operator authority; escalate its named refusal and recovery. Every Yoke self-release run — the stage run over HTTPS as well as that self-deploy — freezes its driver at the run's `release_lineage` (a detached worktree) so the release's own code drives, rehearses and migrates, syncs its runtime dependencies from that checkout's uv.lock, and launches its checkout-owned Python so a merge landing mid-run cannot mix already-cached modules with files read later from disk; remaining drift halts by name (`deploy driver source drift`) without failing the run, and re-drive of the same run id still recovers it by correlation token. The driver records itself on the run (`deployment_runs.driver_attachment`) before that freeze — session, pid, machine, attached_at, heartbeat, phase, and the progress capture it will write — so a second execute of a still-live attachment refuses by name, `watch_tail` consults that fact before blaming missing capture flags, and steering does not treat a `created` run with a live driver as waiting to be driven. Attaching and releasing both take the run row, and the table lock their write needs, under a short `lock_timeout` and **skip rather than wait**: a heartbeat that queued behind another transaction would stop reporting the liveness it exists to report, and a release that queued would keep a SIGTERMed driver alive inside its own shutdown. A skipped attempt prints `deploy run row lock blocked:` naming the holding pid, its age and its state, and the deploy watcher promotes that line to the user-facing stream. A holder reported `idle in transaction` is an abandoned client, bounded by `idle_in_transaction_session_timeout` and released without an operator; the recovery is unchanged, re-run the same `yoke watch deploy -- RUN_ID`, which re-attaches to that run rather than starting a second one. A release that skips prints its named reason and still lets the watcher finish with its exit sentinel. Run creation serializes only against other creation, so a slow composition check never stalls a running driver's heartbeat. An empty or stale attachment (heartbeat older than ten minutes) is an interrupted driver, recovered by re-driving the same run id; re-driving from the machine the recorded driver ran on supersedes it as soon as that pid is gone, because only that machine can see its process table. Never go looking for control-plane database credentials to deploy a project: they are not the project's application database credentials, and a project whose control plane someone else operates has none to obtain.

## Binding-based multi-project delivery

A `github-actions-workflow` stage may declare `input_bindings`, naming another
registered project's branch: `{"consumer_sha": {"project": "other", "branch":
"main"}}`. The build that stage dispatches ships that project's code alongside
the run's own candidate, so the run delivers two projects, not one.

- **Composition records the source; consumption seals it.** The run records
  each bound project's exact commit in `deployment_runs.bound_sources`, beside
  its own `release_lineage`. Before a bound stage dispatches, the runner may
  refresh an unused source to its declared branch's current head. That write
  records old/new commits and re-derives carried work, membership and containment.
  Facts for unchanged sources stay fixed. Existing member requirement snapshots stay fixed; newly admitted members get
  their own snapshots. Read the pins and history with
  `yoke deployment-runs get RUN-ID bound_sources`, and flow bindings with
  `yoke deployment-flows stages FLOW-ID`.
- **A release attributes the commits it wrote itself.** A promotion that
  rewrites a version pin pushes a commit no backlog item authored, into the
  range the next release reads. The producing run records it — `yoke
  deployment-runs release-output record RUN-ID --project P`, stored as
  `outputs` on that project's `bound_sources` entry — and carried-work
  attribution reads that record only for a commit no item claimed, so the
  item always wins; other commits ship as work made outside Yoke. Omit `--commit`
  and the branch the run itself bound names the commit. Recording is refused
  by name for a commit an item already owns, one the run merely pinned, and
  one that does not descend from that pinned source.
- **The record waits for its own column; the release does not.** The column
  is additive, so it arrives on the boot converge of a build carrying it —
  and that build is deployed by a run this same code drives, against the
  database as it stands before that converge. During that one window the
  branch still resolves and the bound stage still dispatches the resolved
  commit; only the durable record waits. Delivery credit for bound-project
  items begins with the first run started after the converge.
- **A branch that cannot be reached refuses the start by name.** It is
  resolved from the bound project's registered checkout, or through that
  project's own authorized repository binding when this host holds no
  checkout; neither answering names both repairs rather than dispatching an
  unrecorded binding.
- **Membership follows the source.** Start-time enrollment runs once per
  project the run ships — its own plus every bound one — against that
  project's recorded commit, so a bound project's delivery-ready items become
  ordinary members. They get a membership row, a requirement snapshot, and the
  item-scoped QA wake when they owe cases. A carried cross-project member
  whose own completion flow declares no item-scoped QA owes no answer when it
  has no explicit plan or post-deploy requirement, and closes with the release;
  reports name its own flow as the reason. Explicit obligations still run. An item whose project
  the run ships no source for is still refused.
  Creation pins bound sources and validates composition in its insertion
  transaction. A refusal rolls back before a run ID is committed; start
  revalidates before stage dispatch. If a stored carried-work record omits a recorded bound
  project, start refuses it by name; cancel that stale run and create a new one.
  Immediately before dispatch, `deployment_runs.execution.bound_sources_prepare`
  resolves the stage's bound branches and records consumption on their source
  entries before returning authoritative inputs and members to the driver.
  An unused stale source re-binds and proceeds. If its containment preview
  races a landing, preparation rolls back its
  writes and locks and retries with fresh preview and apply, at most three
  attempts. Exhaustion reports `candidate_containment_attestation_stale`;
  re-drive the same run. This retry does not repeat backup or rehearsal.
  Once any stage consumed that
  source, a moved branch still refuses — `stage 'S' was not dispatched: bound
  source P SHA is stale (current SHA)` — and requires a new run. A retry copies
  consumption and cannot reopen it. A crash after preparation keeps the source
  consumed because a provider attempt may be ambiguous. Existing durable
  dispatch intent and later stage position also protect previously driven runs.
  Unreadable source or composition evidence refuses with its repair; no inputs
  dispatch on missing proof. A recorded release-output head whose first parent
  is the bound commit still counts as current, so a sibling's version pin does
  not invalidate the pair. The read-only freshness diagnosis remains available
  through `deployment_runs.execution.bound_sources_current` and failure trace.
  A carried delivery-ready item with no completion flow also refuses: select
  its project workflow default with `yoke workflows delivery-default set
  --project P --workflow W --flow F`, then retry the start. Unreadable source
  or landing containment refuses with its item and recovery instead of silently
  omitting membership.
- **Delivery is judged per project.** An item counts as delivered by a
  succeeded run whose recorded commit *for that item's project* contains its
  merge. That is why a bound-project item needs no second run on its own flow
  to record a delivery the carrying run already made — and why a run that
  carried nothing for a project delivers nothing for it, however recent.
- **One commit per project per run.** Two bindings naming the same project
  with different branches are refused: delivery could not then say which
  commit the release shipped for that project.

## QA across release targets

Verify on production by default. A plan case names a non-production target
(an environment without `role.production: true`, such as stage) only with a
`stage_reason` of `creates_or_destroys_data` or `changes_infrastructure`;
authoring refuses `stage_reason_required` otherwise. Each such case enrolls its
item on the stage run, so a read-only check that production can prove belongs
on production alone.

A release pair can admit the same item to both target runs. A supplemental
persistent-environment run enrolls only members with explicit post-deploy
obligations for that environment; untargeted cases remain with final delivery.
Each run freezes only obligations its QA target can answer. Custody for one
QA target does not reserve another target or the final delivery. Composition
continues to name obligations no composed member run can answer. Holding is
per target environment: final-target holders keep final-delivery custody when
later intake changes, and only a holder on the supplemental run's own
environment and exact item-project commit holds its targeted obligations.
A pre-admission holder without a snapshot or selection also needs that same
commit; an older stage pass cannot exclude an item from a new stage release.
A production run
that pinned or delivered the stage run's commit never holds an item away from
the stage run that owes it stage QA. A production run that neither pinned nor
delivered that item-project commit does hold it, and the skip notice names
that commit, because stage proof credits only against the commit production
pins or ships (a hosted promotion ships the commit in its promotion receipt).
`deployment-runs add-item` warns `supplemental_proof_not_credited` when the
stage proof it would compose is on neither commit. Target
splitting uses recorded selections through unlocked, set-based reads.

All records, claims, receipts and QA evidence remain on the connected control
plane. The deployment execution target supplies the stage URL and deployed
revision; observing stage requires no stage control-plane connection. The
item's completion flow remains its final delivery authority. Its done gate
requires accepted admitted copies for every stage and production obligation,
so passing production cannot hide a failed or pending stage case. A run
settles on its own target: the production run succeeds once its own
obligations pass, leaving a member that still owes post-deploy QA or manual
acceptance on another named target at its release wait with `deployed_to` stamped. That member closes against the production
delivery when the stage run accepts its obligation; a member red on the
run's own target or an untargeted manual acceptance still holds the run.
No deferral passes, waives or retracts acceptance. Refusals identify the item,
requirement, phase, target and recovery. Recreating a run does not repair an
ineligible takeover. Startup prepares source facts outside item/run locks,
revalidates mutable facts under bounded locks, and preserves unknown outcomes
on response loss; follow [deployment start diagnostics](../../reference/deployment-start.md)
before retrying a request or changing its run to failed.

## Related

- [Release-time roles](release-roles.md)
- [Pack capabilities](packs.md)
