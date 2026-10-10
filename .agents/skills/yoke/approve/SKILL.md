---
name: approve
description: "Record your decision on a deployment run paused at a Yoke human-approval stage."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "RUN-ID [--note \"...\"]"
---


<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

# /yoke approve RUN-ID [--note "..."]

One decision for one exact run; its current stage owns member synchronization.

## Phase map

| Phase | Read |
|---|---|
| Record or inspect a decision | Execute below |
| Decide whether to resume | Result below |

## Execute

```sh
yoke deployment-runs approve RUN-ID [--note "..."] --json
```

Requires an existing executing run, a current flow stage using human-approval,
and caller authority under that stage's policy without a prior decision.
The optional note records the operator rationale. A refusal stops with its
exact structured error; never force another stage or approve a terminal run.

## Result

Read `stage_approved` and `approval_progress`. Under `any` one approval settles;
under `all` outstanding decisions keep the stage gated. If false, report
`approval_progress.outstanding` and stop without resuming;
`DeploymentApprovalGranted` is not emitted yet.

If true, the decision request is resolved and that event records run, stage,
actor, session, note and members. Resume the exact run's deployment pipeline
from authoritative `current_stage`; create no separate run/item updates or
external approval record.

To inspect without deciding, first read the stage:

```sh
yoke deployment-runs stages RUN-ID
yoke deployment-runs stage-approval evaluate RUN-ID --stage STAGE --json
```

The serving build computes satisfaction/outstanding actors and creates the
policy's decision request when needed. It never approves; a run standing at a
different stage refuses evaluation. Read the operation's help before acting.
