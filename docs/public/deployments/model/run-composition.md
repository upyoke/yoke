# How a run picks its members

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Deployments](../index.md) > Run composition
<!-- /yoke:breadcrumbs -->

Read how creation and start complete a run's membership from its candidate, how custody is asked of a landing, and what freezes before execution.

## Composition completes candidate membership

**Composition completes candidate membership.** Run creation and item-bound
composition (`deployment_runs.start_for_item`,
`deployment_runs.validate_composition`) enroll every delivery-ready item the
pinned candidate carries and the run does not hold, through the same admission
validation `add_item` uses. Creation validates provisionally in its insertion
transaction and rolls back on refusal. It runs that validation twice in one read
scope: first before the creation lock, on a provisional `run-unlocked-*` row
that is always rolled back and whose verdict decides nothing, so the repository
reads (bound branch heads, commit comparisons, containment) happen outside the
lock; then under the lock on the real row, re-checking database facts against
those same reads and re-deriving any comparison whose preceding release changed
meanwhile. `deployment_runs.execution.context` revalidates before dispatch. Its
driver reuses that context once; [start diagnostics](../start-diagnostics.md)
explain containment-only refresh, batched reads, and flushed timing records.

Creation pins bound sources and checks every shipped project; start revalidates
the same composition before dispatch. Independent admission, flow, and
attribution blockers are returned together with their identities. A stored
record missing a recorded bound project refuses with cancel-and-recreate
recovery. That candidate set is two sources unioned before any lock is taken.
The first is `carried_work` above — what this run adds over the run before it.
The second (`deployment_run_unheld_candidates.unheld_candidate_ids`) exists
because the first is a commit *range* and so has a floor at the previous
succeeded release: a landing behind that floor is outside every later range
permanently, so a cancelled or superseded run can leave members behind that
floor; the second source recovers those unheld landings. The second source walks
the run's carried projects for items that are merged, still open, delivery-ready
under their pinned workflow, whose newest landing this run's own pinned lineage
contains, and which no release holds; only definite containment enrolls;
`not_contained` waits for a later candidate, while `undetermined` refuses with
the item, reason, and recovery so unknown attribution cannot silently omit a
member.

**Custody there is asked of a landing, not of an item**
(`delivery_landing_custody.landing_custody`): an item may land several times and
those landings may straddle releases, so a run holds a landing only when the
item is one of that run's members *and* the run's pinned lineage contains that
landing's commit *and* the run is `created`, `executing`, or `succeeded`.
Membership alone over-answers — a membership predating a newer merge is not
custody of it — and containment alone over-answers in the other direction, since
every release cut after a merge contains it including releases that never named
the item. The four states are `held`, `remerged` (member runs exist, none
carries this landing), `unheld`, and `undetermined`; the first and last enrol
nothing. The landing's identity is `item_merge_identity` — the merge commit the
item's newest receipt names — so custody compares the same identity the
close-out gate does, while `merged_at` and `merge_queue_landed_at` decide only
whether an item landed at all, never which landing. Enrollment takes the item
workflow-binding locks and then the run row, the order
`lock_run_with_stable_membership` and `add_item` already use, and locks every
carried item rather than only the currently eligible ones, so eligibility cannot
move between the decision and the insert; a run that is no longer `created`
enrolls nothing.

**Custody is resolved once, before any of those locks, and handed to every
reader** (`deployment_run_unheld_candidates.resolve_candidate_custody`,
returning a `CustodyResolution`): enrollment, the carried-membership refusal,
the unclosable-final-member refusal and the skipped-candidate notice all need
the same answer, so one resolution avoids repeated network containment reads
while holding the run row lock.

**Containment is answered per project, not per item**
(`deployment_run_candidate_range.candidate_range_commits`): one first-parent
comparison from the previous succeeded release to the candidate lists every
landing the candidate added, and a landing on that line is contained without its
own repository read; only a landing outside the range (older than the previous
release, or carried under another commit id) asks the source item by item. A
holder run pinned to the same lineage reuses that answer, and an unreadable
range falls back to the per-item question rather than refusing. Because custody
is asked with `exclude_run_id` set to this run, enrolling its own members cannot
change the answer, so one resolution stays valid for the whole composition. A
reader handed no resolution still walks for itself, and each keeps the behaviour
it had on an undeterminable custody: enrollment raises it by name, the narrowing
readers degrade to no exclusion. Composition freeze then verifies rather than
completes: the driver read its members before reaching it and seeds QA and
stamps release against that list, so a member arriving at freeze would execute
unseeded, and freeze refuses by name instead. An item-less environment run on a
v2 flow enrolls like any other, and deliberate member choices — an explicit
`progress` intent included — are never rewritten.

**Composition names what it skipped in one notice**
(`deployment_run_skipped_candidates.skipped_candidate_notice`): carried items a
live or succeeded release holds; carried items back in rework, whose status is
before their workflow's release stage (under `release_stage` delivery a stage
inside an implementation skill's segment is not delivery-ready unless it is the
release wait itself, so a Dash sent back to `implementing` after a landing is
never composed); members an operator removed; and dependents of a blocker that
has not shipped — a blocker a live or settling release holds included, named
with that run, since composition counts only a recorded `succeeded` delivery as
shipped while completion authority reads a settling run as delivered. Members an
operator removed are subtracted ([removal](../removal.md)). A carried
delivery-ready item with no resolvable completion flow refuses with the item and
flow-selection command named; select a project workflow delivery default before
retrying the start. Other refusals include a carried item whose project or stage
this run cannot admit, an underivable carried set; refused creation rolls back
the run, so there is no run to update. A commit no item owns ships freely with
its SHA, subject and author recorded under its project, and a retry (recorded
`retry_of`; a takeover is not one) of a run that already froze its members
reuses that membership rather than deriving against a moved baseline.

Composition warns for a carried item merged but not at release yet: start
enrolls it once it reaches release, never early. Create refuses with
`release_stranding_unreleased_blocker` if it would strand a carried dependent;
retry once the blocker is at release.

## Bound sources

Before a stage first consumes a bound project,
`deployment_runs.execution.bound_sources_prepare` may replace a stale pin with
the declared branch's current head. It records `rebindings` (from/to commit,
stage and time), re-derives carried work and admits newly carried members
through existing custody, dependency and target rules. Recorded carried-work
facts for the carrier and unchanged bound projects stay fixed. Existing
requirement snapshots remain fixed; new members get snapshots. Containment is
refreshed against the candidate. The source's `consumed_by` and `consumed_at`
are persisted before dispatch; retries copy them, and a moved consumed source
still requires a new run unless the current head is recorded release output
whose first parent is the frozen commit. If promotion pushed its pin before
recording output, finish that record and re-drive the same run to preserve its
frozen input. Other movement stays stale. Source walks happen before item/run
locks; changed preparation state refuses a same-run retry. Missing or unreadable
evidence never authorizes dispatch.

## Admission freezes before execution

Definition-schema-v2 runs freeze admission before execution. The candidate
`release_lineage` must be a full commit SHA; every nonterminal delivery-ready
change carried by that candidate must be a member, while done history,
merge-only flows, Task items, and Epic task graphs are not admitted implicitly.
The run records the shared artifact identity, an immutable composition digest,
the effective flow for every member, and full recoverable QA requirement/plan
content. Missing first-baseline attribution must be resolved explicitly before
start. Cancellation preserves the frozen evidence. Schema-v1 runs retain their
legacy start behavior.
QA acceptance, target occupancy, takeover selection and audited member removal
read complete frozen plan/case selections, never a later standing publication.
Admission freezes attached post-deploy plans and plans named by admitted
requirements. A newly selected plan freezes its complete definition before
its first executable requirements, in the same transaction. Explicit
rematerialization owns authorized updates; withdrawals and replacements retain
their usual effect. Candidate ancestry checks still apply to frozen sources.

An admitted or already materialized selection missing its complete frozen
contract refuses as `qa_frozen_plan_snapshot_incomplete`. Preserve the run and
ask the control-plane operator to prepare a reviewed repair from original
admission evidence through `operator.data_repair.run` before resuming an active
run. Do not import current cases as historical acceptance. Historical requirement
and result records remain viewable without reconstructing an executable plan;
terminal history requires no rewrite. Missing original descriptive metadata
must be recorded truthfully; method configuration contracts, effective policies,
source/target identity, case order and baseline variants require original proof.

## Related

- [Runs](runs.md)
- [Run members and QA](run-members.md)
- [Removing an item](../removal.md)
