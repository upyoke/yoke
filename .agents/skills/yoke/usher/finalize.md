# Usher — finalize

Read live item/run state, then print per-item done, paused or halted with
actual PR/run, stage, failure/approval reason and completed/paused/halted/run
counts. A halt row keeps its halt-class audit reason; never call it completed.
List each created run's project, flow, target, members, status and exact resume.
Terminal success alone permits completed; merge or push is not release proof.

## Resume and recovery

Done skips. Already-landed items skip landing and enter declared delivery;
resume approvals/failures from the existing run's authoritative stage.
Partial batches retain each landed/completed receipt rather than replaying it.

```text
yoke deployment-runs get RUN-ID
yoke deployment-flows stages FLOW-ID
```

Classify the actual failed stage/log. External infrastructure signals include
Actions secrets/dispatch/offline runners/App credentials, SSH host/key/network,
third-party credentials, and provider permissions/throttling/DNS/outage.
Name the specific component and capture the underlying issue through /yoke idea
or field-note as authorized, alongside current-run recovery. A code-class failure
belongs to the current item; no external-infra follow-up replaces its fix.

Resolved/transient failures retry the same run:

```text
yoke --env CONTROL_PLANE watch deploy -- RUN-ID
```

A serving-API self-deploy refusal goes to its control-plane operator with
named recovery. Abort through the registered run writer:

```text
yoke deployment-runs update RUN-ID status failed
```

Items remain at delivery wait unless a declared authorized rollback is taken.
Preserve failed run history; never mutate it to succeeded as a shortcut.

## Claim release and close

Successful terminal items release only claims still held by this session,
reason completed. Halt branches already released with
usher-halt-merge-failure, usher-halt-deploy-infra-failure,
usher-halt-deploy-stage-failure or usher-halt-unexpected; do not release again
or overwrite release_reason_intent. Contention uses handoff-to-usher.

```text
yoke claims work release --item PREFIX-N --reason completed --json
```

Attempt each owed release even if another fails; name failures/holders in the
report. Release waits retain claim/park under the current worker mandate.
Before any nonterminal stop, checkpoint live stage, committed/dirty state,
receipts and next command. A level_change handoff takes precedence over wait.
Send Fleet DONE/END only at actual terminal when the mandate requires it,
with DONE before releasing a claim still held. Never create a run when the
mandate reserves batching to the orchestrator.

Run-based groups execute once under project DEPLOY holds, seed QA automatically
and close members through selected-flow evidence. Proven premerge ephemeral
stage alone allows from-stage continuation; unresolved preview/environment/
lineage/occupancy choices remain explicit operator decisions.
