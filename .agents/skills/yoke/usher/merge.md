# Usher — merge

Deploy-only/resume skips to [deploy](deploy.md). Otherwise process collect's
dependency-safe order, one item at a time. Any unresolved failure halts the
batch with landed items, failed item, live stage, claim outcome and recovery.

## Live binding and evidence

```text
yoke workflows item get PREFIX-N --json
yoke workflows version get {workflow_id} {workflow_version} --json
yoke items get PREFIX-N status merged_at deployment_flow --json
```

Use the pin's logical version, never current registry version. Locate live
stage in the exact ordered definition; select its unique half-open binding
(from_stage_id <= current < through_stage_id), which must be Usher.
Done skips; declared release wait proceeds to delivery. A durable merged_at
at pre-release review reuses yoke merge item close-out; never land again.
Unlanded merge-ready stage continues. Others stop with live pin/receipt facts.

Before release/landing, require every blocking verification requirement
satisfied on its current candidate or explicitly waived. Read requirements
and their current executions rather than treating failed SQL as zero:

```text
yoke qa requirement list --item PREFIX-N --json
yoke qa run list --requirement-id {requirement_id} --json
```

For verification-phase Browser method cases (browser-check or
browser-inspection), require current candidate proof, not a historical pass.
Latest execution is selected by the registered reader, not any historical
pass. Require native case_outcome and runner currency. Unreadable, stale or
unsatisfied evidence stops with the requirement and actual runner recovery.
Browser/e2e requirements are not satisfied by a preview URL or ephemeral
workflow success. No absent-field or default-zero bypass.

Walk only declared adjacent transitions inside Usher. Never hardcode
implemented -> release. For an already-landed receipt, yoke merge item enters
the pinned wait (skip-status delays done only). If the pin requires premerge
release entry, use its exact live source/target through lifecycle.transition
and read the result. A refused gate leaves its recorded stage.

## Premerge ephemeral proof

Read the projected deployment_flow.value and its exact stage definitions:

```text
yoke deployment-flows stages FLOW --json
yoke item-worktrees list PREFIX-N --json
yoke projects capability-settings get --project PROJECT --cap-type ephemeral-env --json
```

No declared ephemeral-verify means no premerge ephemeral run. Failed flow
read is unresolved, not absent. Resolve stage config.workflow, verified App
github_repo, capability preview_domain, and every permitted registered
lane's actual branch and full committed HEAD. Missing inputs refuse by name.
Only relevant current accepted Browser/ephemeral proof for all affected lanes
can skip its runner; an unrelated pass cannot.

The retained external step-runner CLI requires PROJECT before REPO:

```text
yoke dev run -- python3 -m yoke_core.tools.step_runners ephemeral-verify PROJECT REPO BRANCH WORKFLOW DOMAIN SHA
```

Capture/await every lane invocation through completion. Zero with real
EPHEMERAL_URL proof marks premerge verification; failure halts and takes
only the pin's permitted rollback with reason ephemeral_verify_failed.
Resolve the next actual ordered stage from the successful stage definition;
from-stage continuation is valid only with proven prior work and that stage.
No invented runner args, swallowed errors or substring-based JSON parsing.

## Landing route

Effective children=epic_tasks with worktrees=worker_and_integration_lanes
selects [generated-task merge](merge-generated-tasks.md); it lands every
registered lane and records the parent. Never merge only the parent lane.
Children=none with worktrees=single_implementation_lane selects the one standalone
boundary. Unsupported combination refuses with both policy values.

```text
yoke watch merge --print-streaming-pair merge-item -- PREFIX-N --skip-status --wait
```

This prints the safe invocation for the caller's manifest wake capability
without merging. Run the printed command exactly once: a native idle-wake
primitive gets the background subscription pair; no or unverified idle wake
gets one foreground invocation. Follow its reported mode and
[Dash merge](../dash/merge.md). Do not choose from the executor, launch origin,
interactivity or relay reachability.

The boundary owns target branch, merge lock, exact candidate, App-bound PR,
publication, QA and receipts. Missing/stale proof is recovered only where
the engine can produce it: methodless acceptance or Command runner. Browser,
Terminal and other substrate evidence cannot be rebound; the named
commit_bound_runner_authority refusal requires actual candidate proof or
declared postdeploy/manual-acceptance posture. Current-item failures are fixed
here, not waived by future items or planned claims. Never substitute raw
done-transition or another entrypoint when lint refuses.

Queue projects never fall back to local landing. Exit9 is admission/ejection/
record-wait coordination: report named reason and requeue after it clears.
Failed required checks with no run in flight are terminal exit1: fix/commit.
Cancelled/never-started checks have no verdict: rerun same boundary on same
head, no fake fix. Read actual result before assuming landing.

Only `background-wake` may release the caller to its armed subscription;
the `in-turn` command blocks inside the invocation you run. A headless
mandate returning landing_pending records PR,
checkpoints and deliberately waits for control-plane wake; rerun same merge
to close out. A stopped landing rebase/re-gates; record-wait exhaustion parks
with observed state. Never poll GitHub to replace the boundary.

```text
yoke github merge-queue readiness PREFIX-N --json
yoke github merge-queue hold PREFIX-N
```

Readiness is point-in-time. Null autoMergeRequest alone is not a stop:
AWAITING_CHECKS, UNMERGEABLE or MERGEABLE entry means arming was consumed.
Before correcting a live queued head, hold it, verifying cleared arming and
removed entry. Deployment waits for real merge_sha and landing_pending false
or absent. A push is not a landing.

## Single-lane exit handling

Generated-task procedure owns its loop separately. Always inspect landed
receipt before rollback; never undo recorded landed state.

| Exit | Required action |
|---|---|
| 0 | landing_pending follows queue wait above; otherwise verified landing proceeds to delivery. |
| 3 | Inspect structured conflict classifications, resolve confidently in actual lane, stage/commit or continue same Git operation, then rerun same merge. Uncertain intent requires operator decision. |
| 1 | Unlanded push/PR/CI/freshness/verification failure: permitted rollback, release usher-halt-merge-failure, halt. |
| 4 | Preserve user files/stash; permitted unlanded rollback, release usher-halt-merge-failure, halt for dirty-state recovery. Read stash list/apply; never discard. |
| 5 | Merge committed, cleanup failed: no rollback. Leave release stage, release usher-halt-merge-failure, halt; report exact view-regen recovery. Query MergeEngineFailed for phase=post_merge_cleanup/merge_committed diagnostic; durable receipt owns landing. Resume skips merge. |
| 6 | Merge never began; retry budget exhausted on held lock. Keep stage, release handoff-to-usher, halt batch and retry after holder/TTL/orphan recovery. Not a failure-class rollback. |
| 9 | Queue coordination above; preserve receipt/stage and follow named requeue/wait recovery, not catch-all. |
| Other nonzero | Distinguish landed receipt first; unlanded permitted rollback then release usher-halt-unexpected and halt with exact code. No fake done or raw substitute. |

Rollback uses lifecycle.transition.execute with actual source/target and
rollback_reason. Release matching intent BEFORE halt summary:

```text
yoke claims work release --item PREFIX-N --reason usher-halt-merge-failure --json
```

Use the table's different intent for contention/unexpected failures.
release_reason_intent preserves terminal halt class; completed belongs only
to success. A failed release names failure class/holder and retained claim;
never print clean recovery while it remains held. No later batch member runs.
Report relevant Merge*Failed/TargetStale/VerificationFailed diagnostics and
exact resume /yoke usher PREFIX-N, with receipts authoritative and events
telemetry. Reconcile dependencies/claims before any authorized override.

After all landings, repeat collect's project-declared CI advisory (verified
App repo, ci_workflow_file, default branch). Failed warns; passed/running/
no_runs skip. Continue to [deploy](deploy.md).
