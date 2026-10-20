# Verification, test execution, and command output

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Verification
<!-- /yoke:breadcrumbs -->

Read [command output](shell-and-cli.md#command-output) before verification;
[verification model](../../verification/index.md).

## Testing

- Test item ids use variables or patterns, never literal `PREFIX-N`.
- Iterate with `yoke watch pytest --impacted main --bounded`. With `ci_workflow_file` it runs on
  CI, so commit first. `--local` is only for a check that ends in about one minute; past that,
  interrupt it, keep the capture as incomplete, commit and run on CI.
- `selection unbounded` means keep testing what you judge relevant; the final gate covers the
  rest. `--local --impacted main --widen` is the CI-outage fallback only.
- Run the full suite once through its case: `yoke qa requirement list --item PREFIX-N`,
  then `yoke qa case run --requirement-id <id>`. Commit before it; workers never push by hand.
  Rerun only after the tree changes.
- Continue a running gate. If its watcher was killed, rerun
  `yoke qa case run`; it rejoins or adopts the CI run for that commit.
- A requirement bound to an item-scoped deployment stage runs with
  `yoke qa plan run --deployment-run-id RUN --stage STAGE --member PREFIX-N`.
- Use `yoke watch pytest` for test roots.
- CI verdict wake-ups need a healthy relay on this machine
  ([CI wake-ups](../../github/index.md#ci-verdicts-and-session-wake-ups)).
- Several lanes: `yoke qa case run --requirement-id N --checkout-path PATH --expected-branch
  BRANCH --expected-sha FULL_SHA`. Follow refusal recovery for `qa_source_lane_unresolved`,
  `qa_ci_source_mismatch` and `qa_published_head_unproven`.


## Unexplained test failure

The item holder may retry once if the change cannot explain the failed test. First message
`yoke say --steering` with the test and CI run URL. A second failure of the same check on
the same inputs belongs to this item. Failed trains use the recorded
[`--retry-flake` path](../../github/merge-queue-landings.md#failed-merge-trains).

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

- Render captures against a universe you name: `YOKE_ENV=<local-env> yoke ui up`. Seed through
  that env. Keep admission tokens out of output; add a `delay` step before a screenshot.
- Formal Browser QA runs post-deploy on production. A local preview is a self-check only.

## Verification failure ownership

- Current-item verification failures belong to the current item.
  Future work grants no waiver.
  Fix it here unless a live conflict or explicit operator waiver applies.
- Use dependency and claim reconciliation before override.
  Override only a live conflict, as a last resort through project steering.
  Route it through `yoke say --steering` and read `yoke claims path override --help`.
- A consumer test this item did not change that fails against a new producer source is evidence
  against the producer. Never edit or weaken it; name the producer commit range or item and
  route it to steering (`yoke say --steering`) or the producer's companion item.
- Record the failure, the claim action and the rerun evidence; never report green by pointing at
  future work.

## Health checks

A check declares `project_scope`, source-tree use, runtimes and capabilities; never branch on a
project slug. N/A is not a pass. Project checks live in `.yoke/doctor/`; see
[doctor](../../operations/doctor.md).

## Related

- [Operating with agents](../index.md)
- [Agent operation homes](index.md)
