# Deployment QA continuity

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Deployment QA continuity
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
command cases check out its project source. Stored targets and digests stay as
provenance and never gate a write.

A failed successor retains inherited QA for retry or another takeover. Explicit
cancellation and genuine member removal retain their cleanup rules. An early QA
pass never bypasses successor deployment prerequisites or human release approvals.

## Retry a failed case after the fix ships

When the successor's QA stage finds an inherited fail and the current release
contains the item's merge, the owner gets one handoff that says to retry. Retry
on the same requirement; this opens a fresh attempt and keeps the prior fail and
its evidence:

```text
yoke qa plan run --deployment-run-id RUN --stage STAGE
```

Do not use `--replaces` for the same case key, and do not rebind the target:
`replacement_case_corrected_in_place` names this retry instead.

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
