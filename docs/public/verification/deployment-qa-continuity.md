# Deployment QA continuity

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Deployment QA continuity
<!-- /yoke:breadcrumbs -->

Fresh item QA resolves the current completion-flow membership, including a
carrier in another project. A selected plan identifies its target environment;
missing or unready delivery authority refuses. Initial run-level orchestration
retains its internal run/stage context.

Takeover preserves private, shared and run-level QA, including pass/fail evidence
and unfinished walks. Continuation, review and cleanup use the execution ID and
current stored owner even before a successor deploys. Snapshots retain start-time
context; browser observations record the build actually served at the authorized
environment, and command cases retain their admitted checkout revision. A failed
successor retains inherited QA for retry or another takeover. Explicit cancellation
and genuine member removal retain their cleanup rules. An early QA pass never
bypasses successor deployment prerequisites or human release approvals.

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
