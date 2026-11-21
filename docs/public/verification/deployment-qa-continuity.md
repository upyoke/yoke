# Deployment QA continuity

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Deployment QA continuity
<!-- /yoke:breadcrumbs -->

Fresh item QA resolves the current completion-flow membership, including a
carrier in another project. A selected plan identifies its target environment;
missing or unready delivery authority refuses. Initial run-level orchestration
retains its internal run/stage context.

Takeover moves QA; it does not copy or restart it. Private, shared and run-level
QA keep their pass/fail evidence, and an unfinished walk keeps its execution ID,
cursor, completed results, host custody and cleanup state. Continuation, review
and cleanup use the execution ID and current stored owner even before a
successor deploys. A pass stays a pass and a fail stays a fail; nothing re-checks
completed results against newer code.

An open walk is never told to wait or restart. Its owner gets no takeover
notice, and the successor's item QA stage does not wake it with `yoke qa plan
run` while the walk is live on that stage and its owning session has not
ended. The carried walk keeps going on its own execution and may pass on the
newer build. When the successor rebinds the walk's requirement, its host
commands and walk-end still run against the frozen case; a change to the
case's instructions, positions or starting run still refuses. Once the owner ends or the walk settles, the next QA check wakes
the member as usual.

For manual-only QA, takeover notices tell a holder without a scheduled wake to
check the evidence and schedule its own next recheck before parking; dispatch
will not wake it for that evidence. A steering recipient must staff the item
so its holder can do this. A manual-only holder with a future scheduled recheck
gets no takeover notice. Members with automatic requirements still receive the
successor dispatch guidance.

QA tests whatever is deployed at the authorized destination. A newer build than
the run delivered is normal, not drift: QA start reports a different served
commit and proceeds, and each deployment-bound browser case records the commit
its environment served at case start (an observation, not a per-step proof).
Once the successor deploys, install steps get its pinned `release_version`,
the candidate check expects its `release_lineage` (so a moved execution that
already recorded a case begins on a channel target without refreezing), and
command cases check out its project source; the stored target and digest stay
as the recorded results' provenance. Fresh attempts resolve the
successor's ready receipt and candidate; before that receipt exists they retain
the predecessor target. Private and run QA materialization resolve each frozen plan's case and host
baseline through its correction lineage within the run, stage and member.
Replacement and supersession links join rows across plans and target digests;
unrelated plans sharing a case key remain separate. System-retracted rows do
not establish a lineage. Existing live requirements rebind in place to the current target. The requirement keeps its ID and
records its previous target. A pass recorded before or after takeover carries
when its destination matches. If a walk completes before the successor reaches
its QA stage, materialization credits the saved pass when the requirement
rebinds. While the successor's item QA still has to credit the pass, the gate
identifies it as carried and says to wait for the stage.
A changed destination still needs a pass. A fail or other non-pass
recorded against the previous target does not count against the current one:
the case reads as not yet run, the steering report does not flag the run for
it, and the driver captures an automatic plan again when the run reaches that
stage. An open shared plan group keeps
its group ID, plan, pinned cases and case IDs, and follows its owning run the
same way: once that run holds a ready receipt the group's target does not
record (a takeover moved it, or its run redeployed), stage dispatch or the next
`yoke qa plan run --deployment-run-id RUN --stage item-qa --plan P` rebinds
every live group case to the current target, keeping `starting_run_id` and the
previous target in `rebound_from_target_json`. Same-destination passes carry;
a group whose walk has begun keeps its target. Separate groups remain separate
subjects.
Successor stage dispatch also materializes members whose live private cases
still name another run, even when those members already have requirements.
Retracted, superseded and shared-group cases do not trigger this refresh;
a second dispatch with current targets leaves the requirements unchanged.
Begun executions and evidence keep their stored targets and digests as
provenance and never gate a write. Their timestamps and observation windows
do not restart when a requirement follows the successor target. An execution
that has run, leased and recorded nothing yet, such as one waiting for its
Test Machine turn, takes the successor's current roster and target when its
owner's `yoke qa plan run` begins it again or the host-turn wake resumes it
with `--resume-execution-id`; it keeps its execution ID, `execution_order` and
host-line place. This holds for member executions and plan-group walks. A
pause in any phase but the pre-case check-in, or a captured first case, means
a case may have acted, so that execution keeps its target.

A failed successor retains inherited QA for retry or another takeover. Explicit
cancellation and genuine member removal retain their cleanup rules. An early QA
pass never bypasses successor deployment prerequisites or human release approvals.

A frozen root is never materialized again while its lineage exists. The newest
chain end (creation time, then ID) decides whether work remains, including
forked history. Passed, pending and operator/agent-discharged heads prevent a
second case. A failed or system-discharged head permits one content correction
on its own plan; unchanged failed content keeps the existing head owed.
`qa plan rematerialize` refreshes a pending head in place and corrects
eligible unpassed cases independently. A pass on any baseline preserves the
case's frozen definition and every baseline row for that subject, even if
the edited plan removes the case or changes its baselines. The next release
uses the edited definition.

## Retry a failed case after the fix ships

A fail recorded against the predecessor's target stops counting once its case
rebinds to the successor's target: the case reads as not yet run, no failure
handoff goes out, and a driver-run plan is captured again at its stage.
While the case still carries the target the fail answered, an inherited fail
whose latest failing attempt was created before this run, in a release that
contains the item's merge, gets one handoff that says to retry. Any other
fail on the current target gets the ordinary handoff: classify it and start
rework or record its blocker. Once a successor receipt is ready, run the plan
again; materialization rebinds the member's open cases automatically:

```text
yoke qa plan run --item PREFIX-N --stage item-qa --project PROJECT
```

An item-scoped stage refuses `--deployment-run-id`. Use
`yoke qa plan rematerialize --item PREFIX-N --stage item-qa --project PROJECT`
when the plan's case content also changed. Failed cases keep their correction
pointers across a target rebind. Begun executions, captures and attempts keep
their frozen targets; a fresh attempt uses the rebound requirement.

## Credit saved completions

Completion and review-submit return success once the verdict is saved. If a
bounded settlement attempt is busy, the result says `settlement: deferred` and
`credited_by: the run driver's next QA check`. The driver credits the saved
evidence and closes accepted members on its next QA check. Close-out only reads
acceptance; it never retries settlement under an item lock. Read
`yoke deployment-runs get RUN` to follow credit. No reconcile is needed.
A lost completion or review-submit reply replays the same request ID through
the durable request ledger; it never pauses the saved verdict.

## Recover communication on the frozen execution

```text
yoke qa plan run --resume-execution-id EXECUTION_ID
```

The execution supplies current ownership and its stored target. Optional source
and item hints must agree. Resume preserves the cursor, start-time context and
custody without new cases. A stale-settled mission uses this exact execution ID
with `--continue-mission`; it preserves the host and original history.
For a lost reply, follow [check-in recovery](standalone-plans.md#recover-a-lost-check-in-response)
with its pause receipts and saved evidence; do not abort or replay the action.

## Related

- [Deployment plan execution](deployment-plan-execution.md)
- [Run membership and takeover](../deployments/model/run-members.md)
