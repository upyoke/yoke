# Onboard Step 8: Hand Off The First Work

Entry: accepted CURRENT-PLAN naming the first work; a deferred or blocked
deploy does not block the handoff. Skip when this run's work-seeding row
already records the handoff: report it and the activation row.
Rows: work-seeding, verification. `lifecycle-readiness` is read live.

Onboarding does not file items. Steering files CURRENT-PLAN's outcomes and
routes each through its pinned workflow; this session becomes that seat.

## Carry the first work's obligations

Before the handoff, CURRENT-PLAN's first outcome states what its item must
carry, so steering files it complete. Read the live facts it depends on:

```bash
yoke project-structure deploy-defaults get --project {project}
yoke qa plan list --project {project} --json
```

Name in the outcome what it delivers and how to tell it is done (steering
files it with that spec); the issues, PRs and session threads it continues; the
project default flow, or none; a reusable QA plan to attach, from a 25-plan
summary page (follow `next_offset` with `--offset`); and review-only test
evidence when step 2 chose that suite. Installer, onboarding-wizard and
machine-connection work attaches the project-owned installer-campaign plan,
never prose or a generic replacement. Write the change through the same
STRATEGIZE claim and CAS recipe as step 1.

## Verify and hand off

Re-read actual checklist, docs and capabilities/bindings; configured is not assumed:

```bash
yoke onboard checklist --run-id {run_id} --json
yoke strategy doc list --project {project} --json
yoke github status --json
yoke events emit --name ProjectOnboardingVerificationCompleted --kind lifecycle --type project_onboarding --source-type agent --project {project} --context '{"run_id":"{run_id}"}'
yoke onboard checklist --run-id {run_id} --row-status verification=verified --evidence verification="checklist, accepted strategy, capability/binding facts and event verified"
yoke onboard checklist --run-id {run_id} --row-status work-seeding=configured --evidence work-seeding="handed CURRENT-PLAN to /yoke steer; first work: {outcome}; deferred until needed: {rows}"
```

Then run `/yoke steer CURRENT-PLAN` in this session. When steering files the
first item, apply the outcome's QA obligations to that ref before staffing:

```bash
yoke qa item-plan attach --item {ITEM} --project {project} --plan-id {plan_id} --transition reviewing-implementation --qa-phase verification
yoke qa requirement add --item {ITEM} --qa-kind implementation_review --qa-phase verification --blocking-mode blocking --requirement-source explicit --workflow-transition reviewed-implementation --success-policy all-pass
yoke qa requirement add --item {ITEM} --method-id command --qa-phase verification --blocking-mode non_blocking --requirement-source explicit --instructions "Run the declared legacy suite for advisory evidence." --expected-outcome "Record the current suite result without gating the item." --method-config '{"command":"{legacy_argv}"}' --workflow-transition reviewed-implementation
```

The two requirements apply to review-only suites only; use the exact legacy
argv and roots from this run's confirmed profile. A truly one-off check with
no reusable plan uses explicit requirements:

```bash
yoke qa requirement add --item {ITEM} --qa-kind ac_verification --qa-phase verification --blocking-mode blocking --requirement-source explicit --workflow-transition reviewed-implementation
```

## Activation

`lifecycle-readiness` verifies itself when the project's first item reaches
done under its own completion obligations; its evidence names that item.
Until then it reads `first_item_not_done` with the steering recovery, and the
run stays open. Resume reports it:

```bash
yoke onboard checklist get --project {project} --json
```

Required unknown/blocked rows still name their recovery; never claim
activation before the row reads verified.
