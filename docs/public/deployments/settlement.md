# Settlement and item completion

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Deployments](index.md) > Settlement
<!-- /yoke:breadcrumbs -->

Read which run can close an item, how a run settles its members, and how a
stuck settlement recovers.

## Membership is not completion

Being a member of a run does not finish an item. A member closes only on a
succeeded run with **completion authority** for it: a run of the item's
selected (or project-default) completion flow, or another project's run that
recorded a bound source commit for the item's project. Carried code, a failed
run, or a same-project run of another flow closes nothing. An empty
unresolved flow is merge-only, so no completion run exists.
`deployment_item_completion_runs.completion_runs` is the one walk the done
gate's delivery fact, source QA and the delivery ladder all read. The newest
such membership is the one read, except that a failed or cancelled run never
shadows a live, settling or succeeded one beside it.

A final-delivery release (a flow that takes delivery custody, at the
persistent tier) therefore refuses, at `validate_composition` and at the
executing freeze, a same-project `final` member it could not close. The
refusal names both repairs: select the run's flow for the item, or cancel the
run and deliver the item on its own flow. `progress` members, previews and
already-completed members are not refused.

A custody-free run, such as the stage half of a release pair, may carry a
member it does not close, and still enforces its own run QA and approvals. It
cannot prove members at an item-scoped QA stage, which needs the member
snapshots only a custody flow freezes, so creation, `add_item` and
`validate_composition` refuse such a run that carries or owes members
(`item_qa_flow_without_delivery_custody`). A memberless item-scoped QA run is
refused (`item_qa_run_without_members`) only when its flow is the completion
flow for delivery-ready items no other release holds. A memberless run that
owes no delivery passes the stage with `item_qa_no_member_owes_target`.

A successful item `done` write atomically publishes `completed_deliveries` in
its `delivery_evidence` stamp facts, naming the owner, member, run, registered
environment and exact candidate. Ordinary dependencies require `done`;
environment-specific dependencies require both `done` and this attribution.
Preflight stamps and accepted QA alone are not completion. A later sibling
failure or run cancellation cannot revoke a completed member, and later
successful environment deliveries append attribution to it. Dashboard and
batched dependency readers consume this same fact.

## One at a time or together

Whether final members close one at a time or together depends on the
selected flow. When it has no run QA and no run approval, each final member
closes on its own once its delivery lands and its own item QA is accepted (or
discharged with no post-deploy obligation), even while a sibling is still
waiting. When the flow has either shared gate, every final member keeps its
claim, lane and session until all item and shared gates pass, and the run and
its members then close together.

Delivered members require accepted item cases and single-member plans, plus
a closed group covering each shared post-deploy plan. Failing or unanswered
requirements still block, and superseded requirements hand the obligation to
their successors. Retracted run requirements are ignored by the done QA gate,
while standing obligations and the item's delivery gate remain in force.

## How a run settles

A run reads `succeeded` only after its close-outs have happened
(`deployment_run_collective_finalization`). Until then it stays `executing`
and records `settling_at`, a durable state that completion authority reads as
delivered for its members' own gates. Settlement then runs in two phases.

**Commit phase.** First, each cleared member's prerequisites are committed:
its `delivery_evidence` rung and its status preflight (materialized QA and
any approval request). These close nothing and are safe to repeat. Then every
member's terminal status and claim release is written on the settlement's own
connection, each member in its own savepoint, and committed once. Members
close together or not at all, even if the process stops part way
(`delivery_member_close_steps`).

Before writing any member, settlement compares the required members with the
cleared and prepared ones. One member's refusal rolls the whole set back: no
member closes, and every claim and lane is kept. The refusal carries the
error code `run_settlement_blocked` and names each member: blocked ones with
their own reason, the rest as held with the run, so nobody repairs a member
that has nothing wrong. A final member the run could not even try to close,
such as one whose post-deploy obligations are unanswered or whose done gate
still has a blocking QA requirement open, holds the run the same way, and
the refusal names each open requirement. Repeating the write changes
nothing, so the deploy driver stops at once with exit 4 (finalization
pending) instead of retrying; it retries only a write that got no answer.

**Effects phase.** After that commit, the closed members' effects run:
replayable satisfied-dependency notices, GitHub sync, terminal lane cleanup,
and ending holder sessions left empty (`delivery_member_close_effects`). No
transaction stays open across this file-system and network work; each
member's database steps commit on their own short connection. Every effect is
idempotent. A failure never reopens a closed member; it keeps the run
settling, naming the member and the failure, until a replay finishes the
effects and marks the run `succeeded`.

Release wrap-up prints each member stamp and close-out step, then confirms
the `succeeded` write; output before a slow operation does not assert
completion. A re-drive does not stamp `deployed_to` again on members already
`done` with that delivery.

## Settlement replays itself

Settlement replays by itself when the blocking record is cleared
(`settling_run_replay`). A recorded verdict, a waiver, a supersession, a plan
withdrawal or a plan execution's end also retries the accepted-member
close-out on every executing run whose item QA accepted the item
(`deployment_member_close_out_retry`). So a member refused mid-run closes when
its blocker settles, and the last recovered member finishes its settling run
without a hand re-drive. If the run still stays `executing`,
`yoke deployment-runs update RUN-ID status succeeded` replays it. A member
already done is not closed twice.

Success also refuses while any non-`progress` member this run has completion
authority for is still at its release wait, naming why: delivery not read as
discharged, a blocking done-gate QA requirement still open, or post-deploy
obligations unanswered.

Residue is cleared on the way through. A member's own release walk opens an
item-level QA execution; when the run scopes that member its own item QA,
the run-bound execution produces the evidence. A live item-level execution
whose cursor never advanced and that owns no result row has produced nothing,
so settlement aborts it with `superseded-by-run-scoped-item-qa`
(`qa_resultless_execution_supersession`) and closes the member. One that did
record a result keeps refusing, and its own walker still owns it.

When a no-change Dash that never opened a lane is left at its release wait,
its holder closes it with `yoke lifecycle transition PREFIX-N --to done`.
That transition still requires the succeeded run, QA and approval.

## Each run settles on its own target

A member whose only open obligations target another environment (stage QA
beside a production release) is delivered by this run, stamped
`deployed_to`, and stays at its release wait without holding the run. It
closes against that delivery once a run on the other environment accepts its
obligation. A member still red or unanswered on the run's own target keeps
holding it. Holding is per target environment: a production holder never
keeps an item out of a stage run that still owes it stage QA.

## Supplemental proof

The delivery evidence ladder may credit a later successful release that
contains the merge. Source post-deploy QA instead reads the newest eligible
completion-flow membership: failed and cancelled attempts do not erase earlier
accepted proof, an active newer member holds close-out, and a later
containing release with no item membership supplies no admitted QA copy.

A supplemental run credits its environment when its recorded item-project
commit (own or bound) contains the item's current landing. Re-merging
replaces the landing and withdraws proof that lacks it. Missing or
unreadable containment credits nothing; `add-item` warns
`supplemental_proof_not_credited` with both commits and the reason and
recovery. Final-target custody never blocks supplemental enrollment.
Same-environment custody covers the same commit and selection, or no
remaining debt; failed proof lets a later stage run enroll the item again.

This lets Stage and Production commits differ in surrounding code, including
later fixes or reverts. Production-target obligations still guard
Production, and other items carry their own QA.

A carried cross-project member whose own completion flow declares no item QA,
and which has no explicit plan or post-deploy requirement, owes no answer:
stage and fleet reports name its own flow as the reason, and it closes with
the release. Same-project members, and carried members whose own flow
declares item QA, still need an answer; explicit obligations always run.

## Related

- [Deployments overview](index.md)
- [Run members and QA](model/run-members.md)
- [Release authority](model/releases.md)
