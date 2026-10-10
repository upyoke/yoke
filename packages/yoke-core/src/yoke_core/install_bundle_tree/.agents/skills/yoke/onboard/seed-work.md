# Onboard Step 8: Seed The First Work

Entry: accepted CURRENT-PLAN; deferred or blocked deploy does not block seeding.
Skip if this run's work-seeding row already records IDs: report them.
Rows: work-seeding, lifecycle-readiness, verification.

## Propose, confirm, then file

Use `workflow.execution_instruction.resolve` for issue-workflow operator instructions for the target project **before**
titles/proposals and apply them to the whole batch:

```bash
yoke workflow execution-instruction resolve --workflow issue --project {project} --full
yoke strategy doc get CURRENT-PLAN --project {project}
yoke project-structure deploy-defaults get --project {project}
```

Propose one independently workable near-term outcome per item, titles within
effective project limit. Infer priority: urgent/broken/blocking high;
future/nice-to-have low; otherwise medium. Never ask priority.
For existing repos, scan current board and search keywords for open duplicates;
merge/drop overlaps before proposal.

Resolve flow first: empty output means no flow — omit the flag; never pass the literal string `none`.
Present titles/priorities/flow once and take
one confirmation for the whole batch; edits refine that list, not per-item approval.

Create one at a time **bare**, read each returned public ref before the next.
When no flow applies, omit `--deployment-flow`:

```bash
yoke items create "{title}" issue --entry-surface harness_skill --execution-instructions-considered --project {project} --deployment-flow {flow_id} --priority {priority}
yoke items create "{title}" issue --entry-surface harness_skill --execution-instructions-considered --project {project} --priority {priority}
```

All enter idea. Refine owns specs; do not manufacture bodies/claims/dependencies
or imagined children through lower-level surfaces. Echo ID and source outcome.

## Preserve the plan's QA contract

Reusable test plan: resolve ID and attach its immutable snapshot to the matching
item at the transition where proof is definition-of-done:

```bash
yoke qa plan list --project {project} --json
yoke qa item-plan attach --item {ITEM} --project {project} --plan-id {plan_id} --transition reviewing-implementation --qa-phase verification
```

Installer/onboarding-wizard/machine-connection completion requires the
project-owned installer-campaign plan: Test Machine case requirements per
declared host baseline, never prose/generic ac_verification/runbook replacement.

Genuinely one-off expectation with no reusable plan uses explicit requirements:

```bash
yoke qa requirement add --item {ITEM} --qa-kind ac_verification --qa-phase verification --blocking-mode blocking --requirement-source explicit --workflow-transition reviewed-implementation
```

Every review-only item gets blocking review plus advisory exact legacy argv,
roots and known condition from **this run's** confirmed profile.
Do not convert to command-ci or blocking registered-command plans just because
another CI system can execute it:

```bash
yoke qa requirement add --item {ITEM} --qa-kind implementation_review --qa-phase verification --blocking-mode blocking --requirement-source explicit --success-policy "Implementation matches the item acceptance criteria under review" --workflow-transition reviewed-implementation
yoke qa requirement add --item {ITEM} --method-id command --qa-phase verification --blocking-mode non_blocking --requirement-source explicit --instructions "Run the declared legacy suite for advisory evidence." --expected-outcome "Record the current suite result without gating the item." --method-config '{"command":"{legacy_argv}"}' --workflow-transition reviewed-implementation
yoke onboard checklist --run-id {run_id} --row-status work-seeding=configured --evidence work-seeding="CURRENT-PLAN outcomes: {created refs and titles}"
```

Rejected create blocks work-seeding with title/error and **already created IDs**;
preserve them and propose only the remainder on retry.

## Verify and hand off

Re-read actual checklist, docs and capabilities/bindings; configured is not assumed:

```bash
yoke onboard checklist --run-id {run_id} --json
yoke strategy doc list --project {project} --json
yoke github status --json
yoke events emit --name ProjectOnboardingVerificationCompleted --kind lifecycle --type project_onboarding --source-type agent --project {project} --context '{"run_id":"{run_id}"}'
yoke onboard checklist --run-id {run_id} --row-status verification=verified --evidence verification="checklist, accepted strategy, capability/binding facts and event verified"
```

Only with actual seeded items and no required unknown/needed/blocked rows:

```bash
yoke onboard checklist --run-id {run_id} --row-status lifecycle-readiness=verified --evidence lifecycle-readiness="first project-scoped items exist: {refs}"
```

Otherwise lifecycle-readiness=blocked names open rows; no completion claim.
Use router handoff: project/checkout/run/rows, docs, Pack versions, redacted
capabilities, environments/flows, URL+smoke or deferral, IDs and blockers.
Point to /yoke steer for staffing or /yoke charge for runnable work.
