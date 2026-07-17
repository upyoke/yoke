---
name: approve
description: "Approve a deployment run that is paused at a Yoke human-approval stage."
argument-hint: "RUN-ID [--note \"...\"]"
---

# /yoke approve RUN-ID [--note "..."]

Approve one exact deployment run inside Yoke. The run is the authority; member
item deployment stages are synchronized by the same transaction.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
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
- its current stage exists in the run's deployment flow; and
- that stage uses the `human-approval` executor.

On success, Yoke atomically advances `deployment_runs.current_stage` and every
member item's `deploy_stage`, keeps member items in `release`, and emits
`DeploymentApprovalGranted` with run, stage, actor, session, note, and member
identity. Do not issue separate run or item updates and do not create an
external approval record.

Then resume the exact run through the deployment pipeline. The pipeline starts
from the newly authoritative `current_stage`.

If approval is rejected, report the exact structured error and stop. Never
force a run past a non-approval stage or approve a terminal run.
