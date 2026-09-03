---
name: approve
description: "Record your decision on a deployment run paused at a Yoke human-approval stage."
argument-hint: "RUN-ID [--note \"...\"]"
---

# /yoke approve RUN-ID [--note "..."]

Record one approval on one exact deployment run inside Yoke. The run is the
authority; member item deployment stages are synchronized by the same
transaction.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `RUN-ID` (required): exact deployment run id, such as
  `run-20260717-003`.
- `--note` (optional): short operator rationale stored in the Yoke approval
  event.

## Execute

Run the registered mutation directly:

```sh
yoke deployment-runs approve RUN-ID [--note "..."] --json
```

The command must succeed only when all of these are true:

- the exact run exists;
- its status is `executing`;
- its current stage exists in the run's deployment flow;
- that stage uses the `human-approval` executor; and
- you hold an authority the stage's approval policy addresses, and have not
  already decided this stage.

**One approval is not always an approved stage.** The stage declares the same
approval policy every Yoke gate declares. Under `any` your approval settles
it; under `all` it records your decision and the stage keeps waiting for the
rest. Read `stage_approved` and `approval_progress` in the result: when
`stage_approved` is false, the stage is still gated, `DeploymentApprovalGranted`
is deliberately not emitted, and `approval_progress.outstanding` names who the
run is waiting on. Report that and stop — do not resume the pipeline.

When `stage_approved` is true, Yoke has resolved the stage's decision request
and emitted `DeploymentApprovalGranted` with run, stage, actor, session, note,
and member identity. Do not issue separate run or item updates and do not
create an external approval record. Then resume the exact run through the
deployment pipeline, which advances from the run's authoritative
`current_stage`.

If the command refuses, report the exact structured error and stop. Never
force a run past a non-approval stage or approve a terminal run.
