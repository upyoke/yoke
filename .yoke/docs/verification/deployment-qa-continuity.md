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

QA tests whatever is deployed at the authorized destination. A newer build than
the run delivered is normal, not drift: QA start reports a different served
commit and proceeds, and each deployment-bound browser case records the commit
its environment served at case start (an observation, not a per-step proof).
Once the successor deploys, install steps get its pinned `release_version` and
command cases check out its project source. Fresh attempts resolve the
successor's ready receipt and candidate; before that receipt exists they retain
the predecessor target. Private and run QA materialization find open cases by
run, stage, member, plan, case key and host baseline, and rebind each
requirement in place to the current target. The requirement keeps its ID and
records its previous target. A predecessor pass carries only when its
destination matches; otherwise the case is owed again. Shared plan groups retain
their group ID and frozen target; separate groups remain separate subjects.
Successor stage dispatch also materializes members whose live private cases
still name another run, even when those members already have requirements.
Retracted, superseded and shared-group cases do not trigger this refresh;
a second dispatch with current targets leaves the requirements unchanged.
Existing executions and evidence keep their stored targets and digests as
provenance and never gate a write. Their timestamps and observation windows
do not restart when a requirement follows the successor target.

A failed successor retains inherited QA for retry or another takeover. Explicit
cancellation and genuine member removal retain their cleanup rules. An early QA
pass never bypasses successor deployment prerequisites or human release approvals.

## Retry a failed case after the fix ships

When the successor's QA stage finds an inherited fail whose latest failing
attempt was created before this run, and the current release contains the
item's merge, the owner gets one handoff that says to retry. A failure
created after this run gets the ordinary handoff: classify it and start
rework or record its blocker. Once a successor receipt is ready, run the plan
again; materialization rebinds the member's open cases automatically:

```text
yoke qa plan run --item PREFIX-N --stage item-qa --project PROJECT
```

An item-scoped stage refuses `--deployment-run-id`. Use
`yoke qa plan rematerialize --item PREFIX-N --stage item-qa --project PROJECT`
when the plan's case content also changed. Failed cases keep their correction
pointers across a target rebind. Existing executions, captures and attempts keep
their frozen targets; a fresh attempt uses the rebound requirement.

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
