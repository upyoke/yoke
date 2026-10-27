# QA requirement state

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Requirement state
<!-- /yoke:breadcrumbs -->

QA authorization is a derived answer over existing requirements, executions,
review audit, definitions and proof. It has no separate persisted state machine.
`qa_latest_execution` owns actual-attempt selection; `qa_obligation_settlement`
owns discharged and replaced requirement predicates.

## Evaluation order

1. Determine the gate's owner, transition or phase, deployment subject and
   environment. Unrelated history does not enter its required set.
2. Honor explicit waiver or retraction. Follow a valid replacement to its final
   effective requirement. Declaration immediately removes predecessor grading,
   even while the successor is pending or failing. Validate same-scope edges,
   environment and execution target, missing successors and cycles in the
   declaring transaction. An empty target digest does not erase environment.
3. Select the newest actual execution by its aware `started_at` instant. Use
   execution id only to break equal starts. Select before considering verdict,
   completion, review, definition currency or proof. Pending and failing attempts
   outrank older passing attempts. Missing or ambiguous start evidence refuses
   as `qa_execution_order_ambiguous`; inspect the named owner and evidence with
   the control-plane operator before correction. Never substitute creation time,
   completion time, review time or id for missing start evidence.
4. Grade that execution's verdict, completion, required judgment and its own
   proof against the appropriate behavioral definition and target.
5. Require all applicable effective requirements to pass, then honor independent
   delivery, acceptance and live ownership prerequisites.

Attempt insertion, judgment and replacement validation serialize within the obligation scope so a concurrent write cannot change the selected attempt underneath automatic discharge or close a correction cycle.

An older unfinished attempt is history after a newer actual attempt. A live
plan execution, process or lease remains separately owned and must finish or
abort before terminal settlement. Selecting an attempt does not release it.
An in-flight host abort first requests cancellation and retains custody until
[case cleanup is proven](deployment-plan-execution.md#stop-host-work-safely),
including restoration only when that case declared a baseline.

A requirement-filtered `qa.run.list` puts that native-selected attempt first
and retains every historical run, including detached review audit rows. Case
detail resolves the explicit `current_run_id` from that same snapshot, independently
of history order. The field is null for empty or unfiltered history; unfiltered
run lists retain their existing audit order. A client missing this response field
refuses with `qa_current_run_identity_unavailable` and names the serving-response
floor; the control-plane operator must serve the release carrying the field.
Merge and terminal close-out read the same selected execution and proof through
`qa_terminal_records`. An older item-detail response missing current proof,
subject proof or human-review fields refuses `qa_proof_response_unavailable`
with serving-response floor `next-release`: use the installed client matched
to that engine, or update engine and client together to the release carrying
this reader. Merge requests proof grading with `qa_proof: true` on
`items.detail.get`; ordinary item-detail reads keep the display summary.
The run writer records a start commit when available, as an observation only,
and preserves a verified commit already in the evidence. The latest completed
pass on the item's effective requirement counts without commit comparison,
including after a rebase or when no start commit was recorded. Required
merge-queue CI still proves the final commit. The landing refuses
`lane_head_superseded` if the branch advanced; retry the merge.
A missing or ambiguous start
refuses the case read with the same named ordering reason as native grading.
Native `qa.run.list` and `qa.run.get` project each run's `case_outcome` through
the shared judged-outcome model. A final review of a `needs_review` capture
therefore reads passed or failed without rewriting its stored capture outcome,
raw evidence or timestamps. Case detail displays that native projection.

## Reviews

Resolving a `qa_needs_review` decision outside a deployment run sends its
outcome, reviewer note and next step to the item's current work-claim holder.
Approval accepts the reviewed evidence, rejection asks for correction and
fresh evidence, and waiver discharges the obligation. Read the named case:

```text
yoke qa requirement get --requirement-id {requirement_id}
```

With no holder, the notice asks the project's steering session to staff the
item and relay the verdict. Queued envelopes remain in steering's undelivered
messages view. If neither holder nor steering is addressable, resolution warns
that manual staffing is required; the saved verdict remains authoritative.
Retries reuse one session notice per requirement and action. Deployment-bound
reviews retain their [run/stage routing](../deployments/model/releases.md#a-human-verdict-reaches-the-agent-that-parked-for-it).
Owner: `yoke_core.domain.qa_verdict_notice`.

A review judges the actual captured run. It does not create an execution.
Plan review audit retains capture id, verdict and rationale; the bundle retains
reviewer actor and session. Responses, artifacts, completion notices and human
decision requests refer to that actual run. Replay of the same review no-ops;
a conflicting final judgment requires a real new attempt.

Historical separate review rows remain audit history. Durable review
associations classify them as judgment-only; a runner label does not. A real
agent execution remains an execution, and a self-referencing review association
keeps its actual capture eligible.

Human escalation resolves the exact run in its decision request. A resolved,
authorized decision may settle that run's provisional `undetermined` verdict to
`pass` or `fail`. The trigger verifies requirement, captured run, action, actor,
resolution time and rationale, and preserves raw evidence and start identity.
Final pass, fail and error verdicts remain immutable. The permanent governed
trigger migration changes no historical row and declares a serving floor.

Reviewing an older capture preserves that capture's audit and judgment. It
cannot make a newer attempt pass or discharge replacements on behalf of that
newer attempt. Only the selected current passing successor may record the
existing automatic passing-supersession effect, on the review transaction.

## Definition and proof

Execution and judgment fields determine behavioral currency: method, runner,
verdict path, instructions, expected outcome, executable config, entry surface,
starting state, required completion, capabilities and meaningful ordering.
Display names and explanatory reason labels do not invalidate proof.

An admitted deployment definition is frozen. Grade it against that admitted
definition; live source edits remain source-lineage diagnostics and retain the
explicit refresh boundary. A source replacement does not silently retire an
admitted copy or the source obligation from which it came.

Explicit item plan rematerialization reaches both source-keyed direct copies
and plan-backed copies on active runs. Plan copies match the source's plan,
case, member, baseline and declared environment. An unjudged copy refreshes
with its source. A copy a live execution has not reached yet refreshes with
its source and its roster entry; an answered copy or a copy the walk already
reached refuses when the refresh would change it, and nothing is written.
Supersede an answered copy, or abort the live execution before retrying
refresh. Discharged copies and copies on terminal runs retain their original
definitions and acceptance history.

Refresh corrects eligible cases in the existing frozen selected plan in the
same transaction as their requirement rows, under the run lock. It resolves
the existing flow or attaching member owner first; missing or ambiguous
ownership refuses before writes. Other owners, unchanged siblings, passed
acceptance, source provenance and execution targets stay frozen. A historical
capture awaiting review remains evidence of its original definition and cannot
prove the corrected definition.
Shared correction may enter through any attaching member; it reaches only
already-frozen owners of that exact plan/source/target group and creates no
selection on a peer whose plan was not frozen yet.

A successful machine capture awaiting independent review preserves intermediate
chain state and permits its immediate inherited follower in the same execution.
The last case restores the baseline; failed captures still restore and block
followers. Independent review remains mandatory after capture completes and
pending captures do not discharge requirements.

Proof must describe the same selected attempt and subject. Code proof records
the observed build identity; an expected release SHA is not an observation.
Browser capture time never substitutes for observed identity. A build may
prove an accepted landing through verified repository containment.
Lane start identity is traceability for every method. Frozen
Machine/mission runners prove the same actual capture through the admitted
case result, baseline, host lease and contract; a direct Machine case uses its
own canonical machine artifact and leased resource without a plan wrapper.
Reviews inherit that identity.
Endpoint Command cases record the URL actually passed to their command and
prove it belongs to the frozen target. Their recorded lane start commit does
not substitute for resource proof. Missing resource proof refuses
with `qa_machine_*` or `qa_endpoint_*`; rerun the named actual case against its
required target. Configuration and document checks retain their appropriate
actual evidence. Do not borrow an old screenshot, passing verdict or unrelated
execution result to complete a current proof chain.

Completion is scoped to target environment and frozen delivery membership.
A cancelled duplicate carrying no QA does not erase an earlier applicable
authoritative delivery. A completed item or delivery stays completed; reads
do not reopen it or rewrite its historical judgments.

## Empty and discharged scopes

These are distinct answers: the applicable workflow requires no QA; an
explicit no-obligation decision exists; every applicable requirement was
legitimately waived or retracted; or required setup is missing. Empty rows alone
do not prove authorization. Keep each disposition and its reason visible.

Requirement aggregation is all-pass. Attempt voting and historical pass rescue
are unsupported. A measured threshold may judge one execution's outcome; it
does not count attempts. See [success policy](success-policy.md).


Integration simulation retains failed reports and all earlier attempts. The
existing PROCEED operation may record a distinct triage discharge only when
the selected report explicitly recommends PROCEED, has no CRITICAL gaps, and
its required follow-up refs exist in the same project. The existing item
structured records retain the exact attempt/capture, report digest, accountable
actor, rationale and filed refs. Events remain disposable telemetry. This
extends the existing adjudication audit instead
of introducing a new table or approval framework. It does not manufacture a
pass or change the failed report. A newer actual attempt invalidates that
discharge. Verification, done and gate summary use the shared requirement
settlement predicate: a current triage discharge settles the simulation
without a passing run or waiver. Summaries expose triage separately from pass
and waiver; a failed simulation without that discharge still blocks done.
The authenticated PROCEED owner requires the acting session's epic claim.
Its item-owned receipt retains the claim, actor, exact raw report, digest,
and capture start and completion instants. Both SQL and Python invalidate it
when any capture evidence changes or the attempt becomes unfinished.
Generic section upsert, append, delete, and full-field replacement cannot
author or replace the reserved `Simulation Triage` receipt namespace;
replay preserves the original audit and refuses a changed capture.

## Successor consistency and repair

Supersession validates the existing correction chain before writing. When a
replacement chain ends at the named passing case, the superseded row's existing
replacement link moves to that same terminal case. Intermediate requirements,
captures and correction history remain available. A different terminal, missing
row, cycle or incompatible obligation refuses as `replacement_graph_invalid`.

For inconsistent links whose branches both reach the same terminal, an operator
or project steering holder repairs through the existing supersede surface:

```text
yoke qa requirement supersede --requirement-id {old_requirement_id} --superseded-by-requirement-id {terminal_requirement_id} --reconcile --source operator --rationale "Why this terminal answers the obligation"
```

Inspect the chain and name its unique terminal before running this command.
Operator-sourced reconciliation requires ordinary same-scope passing proof and a
live steering seat covering the requirement.
That authority is sufficient without the item's work claim; the claim alone is
insufficient. Coverage uses the item's live strategy-document membership.
The repair retains prior rationale and supersession time, appends the actor,
seat claim and scope, previous links and repair rationale, and notifies the item
holder through existing routing while retaining its claim. The receipt reports
notice delivery and recovery if notification fails. Supersession without reconciliation
keeps its ordinary QA subject claim policy.
Ambiguous branches refuse before writing; ask the operator to resolve the
intended obligation instead of guessing a successor.

## Links that stop answering for their obligation

A link is valid only while both rows bind the same obligation scope and the
successor is blocking. Every link writer checks that when it writes. Two
writers can change a linked row afterwards: `yoke qa requirement update`
(`target_env`, `qa_phase`, `workflow_transition_id`, `blocking_mode`) and
`yoke qa requirement rebind-target`. Both refuse with
`replacement_link_scope_changed` and write nothing when the change would break a
link into or out of the row. The refusal names each broken link and the repair.

A change to the scope rule itself can still leave a stored link that was valid
when written. The done gate then refuses with the `replacement_graph_invalid`
error, naming both rows, the differing scope and the repair, rather than
reporting missing proof. A plan read (`yoke qa plan get`) reports the same error
on the affected case instead of failing: that proof's outcome is
`replacement_graph_invalid`, its `replacement_graph_error` names the rows,
reason and repair, and the plan stays unsatisfied. Repair the predecessor with the reconciliation above,
naming a passing same-scope case. Reconciliation replaces a direct link that no
longer answers for the obligation rather than following it. Waive the
predecessor when no passing same-scope case exists. Links held by a waived or
retracted row carry no obligation. The gate and the writer guards read one rule,
so any change to the scope rule reaches both.

Failing or cancelling a deployment run aborts its live plan executions and
retracts its unsettled run-bound requirements in the same transaction. Host
reservations and leases release through execution settlement. An execution
already under a recorded abort is left to that abort: it keeps its host until
its own cleanup proof settles it. Current passing
evidence and standing item plans remain; a later release materializes fresh
copies. Retraction records the run and reason; it grants no passing verdict.
Retrying a failed run restores only its automatic retractions and requires a
new walk; manual retractions and terminal execution histories remain intact.

Removing a member (`yoke deployment-runs remove-item`, or a run takeover)
aborts that member's live executions with reason `deployment-member-removed`.
A runner checked in on a host case, or a mission walk holding its Test Machine,
instead keeps custody and heartbeat authority under the cooperative abort `yoke
qa plan abort` records. Its check-in reports `abort_requested`; its cleanup
proof (`as_is` needs no restore) or the walk's `yoke qa mission walk-end`
settles it and frees the host, which no waiting execution gets first. A gone
runner's recovery: "Stopping a host case" in `yoke qa plan run --help`. The runner's abort response returns the execution's `release_reason`. When it
names the removal, `yoke qa plan run` reports the case as `case_outcome:
removed` with plan state `removed` and exit status 1, not as a host-control
error. QA was cancelled, not passed, and no host needs repair. The item owes
its QA in its next release.

An aborted or errored execution retains a typed review bundle for its completed
captures. Its owner retrieves that bundle through `qa.plan_review.begin`:

```text
yoke qa plan review-begin --item PREFIX-N --execution-id ID
```

For a run use `--deployment-run-id RUN`; for a standalone plan use `--project P`.
Review-begin and the returned artifact-read commands use the universe's serving
evidence plane; see [reading a capture](browser-evidence.md#reading-a-capture).
Use the returned `review-submit` command to judge the captures independently;
unwalked cases remain unfulfilled and the execution remains terminal.
Incomplete captures without review authority settle as errors. The stop wakes
the capture session, else each member's holder (adopt first); the stage blocker
names this command and new rosters skip those cases until review.

After restaffing, the successor first acquires the execution item's work claim,
then explicitly adopts the existing execution through `qa.plan_execution.adopt`:

```text
yoke qa plan adopt --item PREFIX-N --execution-id ID --reason "Continue captured QA after restaffing"
yoke qa plan review-begin --item PREFIX-N --execution-id ID
```

For deployment QA, replace `--item PREFIX-N` with `--deployment-run-id RUN` in
both commands; the execution identifies its member or requesting item. Adoption
requires a registered predecessor with `ended_at` or `terminated_at`; heartbeat
silence, a parked session or a missing session row never authorizes transfer.
It records the previous/new actors and sessions, work claim, reason and time in
`qa_plan_execution_adoptions`, atomically with the ownership change.
Captured approvals, artifacts, cursor and review bundle identity stay intact.
A live execution can continue using its original command plus
`--resume-execution-id ID`; its source, unknown-action and host-custody checks
still apply. Adoption never revives a released host lease or terminal execution;
review an aborted execution's completed captures instead. Steering settles one
it cannot adopt: [reconcile](../functions/qa.md#reconcile-a-stranded-execution).

This command requires a serving release carrying `qa.plan_execution.adopt`.
A serving-floor refusal names the minimum release; ask the control-plane
operator to supply that release before retrying.

Verdict writers automatically record the actual plan execution id and its
concrete artifact ids beside other proof. A deployment-stage verdict also
re-evaluates active acceptance after commit, using the same frozen-target gate
as the driver. Missing evidence still blocks; recording a verdict supplies no
fabricated proof.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
