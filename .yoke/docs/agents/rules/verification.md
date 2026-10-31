# Verification, test execution, and command output

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Verification
<!-- /yoke:breadcrumbs -->

First read [command output](shell-and-cli.md#command-output).
Model: [verification](../../verification/index.md).

## Testing

- Never put literal `PREFIX-N` item ids in tests; use variables or pattern matchers.
- Iterate with `yoke watch pytest --impacted main --bounded`. In a lane it first brings the lane
  current with origin; uncommitted work or a conflict refuses with the reason and fix and runs no
  tests. With `ci_workflow_file` it runs on CI, so commit first. `--local` is only for a check that ends in about one minute; past that,
  interrupt it, keep the capture as incomplete, commit and run on CI.
- `selection unbounded` means keep testing what you judge relevant; the final gate covers the
  rest. `--local --impacted main --widen` is the CI-outage fallback only.
- Run selections before the QA case. A selection follows a running or green full CI run on its
  commit and refuses a near-full selection, naming the QA case command.
- Run the full suite once, through the attached case: `yoke qa requirement list --item PREFIX-N`,
  then `yoke qa case run --requirement-id <id>`. Commit before it; workers never push by hand.
  Never run the full suite twice on the same tree; rerun only after changes.
- A quiet or backgrounded gate is still running: continue it. If its watcher was killed, rerun
  `yoke qa case run`; it rejoins or adopts the CI run for that commit.
- An item case bound to an item-scoped deployment stage runs with
  `yoke qa plan run --item PREFIX-N --stage STAGE`. An attached post-deploy plan runs once
  per release as a plan group:
  `yoke qa plan run --deployment-run-id RUN --stage item-qa --plan PLAN`.
- Never run raw `python3 -m pytest` over whole test roots; use `yoke watch pytest`.
- CI verdict wake-ups need a healthy relay on this machine
  ([CI wake-ups](../../github/index.md#ci-verdicts-and-session-wake-ups)).
- Several lanes: `yoke qa case run --requirement-id N --checkout-path PATH --expected-branch
  BRANCH --expected-sha FULL_SHA`. Follow refusal recovery for `qa_source_lane_unresolved`,
  `qa_ci_source_mismatch` and `qa_published_head_unproven`.

## Failing or flaky tests

A failing or flaky test is a defect. Never re-run unchanged inputs to get a pass; Yoke
refuses it.

- Caused by this item, or in a file this item touches: fix it here, commit, and re-run the
  gate. This includes a test that passes and fails on the same commit.
- Not caused by this item: run `yoke feedback --to universe --category failed --evidence
  'Flaky test: TEST, CI run URL, observed outcomes'` (add `--correlation-id` for repeat
  evidence), then `yoke feedback promote ENTRY --title 'Fix flaky TEST'`. Then wait on
  the fix item with the existing recipe in
  [delivery.md#wait-on-another-items-merge-or-delivery](delivery.md#wait-on-another-items-merge-or-delivery)
  (`yoke items dependency add THIS-ITEM FIX-ITEM dash --gate-point integration
  --satisfaction fact:merged --rationale '...'`, then `yoke sessions touch --mode parked`).
  The gate stays red; the fix item's landing wakes you. If the fix is small and the work
  claim allows its files, fix it in this item instead.
- Cancelled or never-started jobs are not a verdict; recover them with
  [failed CI job recovery](../../github/index.md#failed-ci-job-recovery).

## QA results

- Judge a result against the item's user outcome first. A case step the product cannot meet
  while the outcome holds is a case defect: repair the case through its registered write and
  rerun. A pass while the outcome fails is a product defect.
- After failed QA: product defect, return to implementation; setup failure, record the blocker;
  unclear cause, investigate now.
- A plan may record another environment, but standalone QA runs only where the runtime allows;
  deployment QA targets what the run receipt authorizes.
- Standalone plans: read `yoke qa plan run --help`. After a lost response, rerun the same command
  with `--resume-execution-id ID` per
  [check-in recovery](../../verification/standalone-plans.md#recover-a-lost-check-in-response);
  an unknown reply is not a failure.
- Failed CI jobs: follow [failed CI job recovery](../../github/index.md#failed-ci-job-recovery).
  Never rerun an older run through another tool.

## Visual evidence

Run browser checks at their specified sizes. Verify UI fixes with rendered screenshots
against the supported deployment context.

- Render captures against a universe you name: `YOKE_ENV=<local-env> yoke ui up`. Seed through
  that env. Keep admission tokens out of output; add a `delay` step before a screenshot.
- Formal Browser QA runs against its declared post-deploy target. A local preview is a self-check only.

## Verification failure ownership

- Current-item verification failures belong to the current item.
  A future item or planned path claim is not a waiver.
  Fix it here unless a live conflict or explicit operator waiver applies.
- Use dependency and claim reconciliation before override.
  Do not use `path-claim-override` for a planned future claim;
  override is last resort and requires a live steering seat covering the project.
  Route it through `yoke say --steering` and read `yoke claims path override --help`.
- Update a test this item's change made stale; never weaken a behavior assertion to pass.
  Follow [failing or flaky tests](#failing-or-flaky-tests) for an unrelated cause.
- Record the failure, the claim action and the rerun evidence; never report green by pointing at
  future work.

## Health checks

A check declares `project_scope`, source-tree use, runtimes and capabilities; never branch on a
project slug. N/A is not a pass. Project checks live in `.yoke/doctor/`; see
[doctor](../../operations/doctor.md).

## Related

- [Operating with agents](../index.md)
- [Agent operation homes](index.md)
