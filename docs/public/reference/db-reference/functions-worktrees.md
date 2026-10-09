# Worktrees Function Catalog

Read [envelope and authority](functions.md) first. `none` means no dispatcher work-claim check; handler permissions still apply. Read command help for the live payload and serving floor.

## Registered functions

| Function id | Claim policy |
|---|---|
| `done_transition.blocked_gate` | `none` |
| `done_transition.delivery_done_notice` | `none` |
| `done_transition.delivery_evidence` | `none` |
| `done_transition.done_preconditions` | `none` |
| `done_transition.epic_task_github_issues` | `none` |
| `done_transition.epic_task_list` | `none` |
| `done_transition.epic_task_status_set` | `none` |
| `done_transition.finalize_local_side_effects` | `none` |
| `done_transition.item_context` | `none` |
| `done_transition.item_field` | `none` |
| `done_transition.item_status_set` | `none` |
| `done_transition.latest_deployment_run` | `none` |
| `done_transition.populate_merged_at` | `none` |
| `done_transition.registered_flow_ids` | `none` |
| `done_transition.run_blocking_qa` | `none` |
| `done_transition.run_stage` | `none` |
| `done_transition.run_stage_qa_acceptance` | `none` |
| `item_landings.list` | `none` |
| `item_landings.record` | `none` |
| `item_worktrees.create` | `item` |
| `item_worktrees.get` | `none` |
| `item_worktrees.inventory` | `none` |
| `item_worktrees.list` | `none` |
| `item_worktrees.path_record` | `item` |
| `item_worktrees.release` | `item` |
| `item_worktrees.release_merged_lane` | `none` |
| `merge.lock.acquire` | `none` |
| `merge.lock.list` | `none` |
| `merge.lock.release` | `none` |
| `merge.preflight.blocked_gate` | `none` |
| `merge.preflight.dependency_gate` | `none` |
| `merge.preflight.epic_task_statuses` | `none` |
| `merge.prune.authority_verdict` | `none` |
| `merge.tests.post_rebase_requirement` | `none` |
| `merge.tests.record_post_rebase_ci_run` | `none` |
| `merge.tests.recorded_queue_receipt` | `none` |
| `merge_queue.landing.observe` | `none` |
| `merge_queue.landing_pending.clear` | `none` |
| `merge_queue.landing_pending.mark` | `none` |
| `merge_queue.landing_pull_request.record` | `none` |
| `merge_receipt.commits.attest` | `none` |
| `merge_receipt.get` | `none` |
| `merge_receipt.record` | `none` |
| `merge_review.candidate.evaluate` | `none` |
| `release_pin.record` | `none` |

## Lane authority and transport

With an empty payload, create idempotently ensures the
sole policy-required default lane. Explicit `lane_role` and `branch` register worker/integration lanes;
the item must be active and claimed, branch project-unique, and path-claim gate
passing. Multiple workers are allowed; second integration or branch-role reuse
refuses. Get selects a lane role and returns null when absent; list preserves
every active lane. Project inventory includes released records for hygiene.

Preparation works over either local Postgres or HTTPS: read the authoritative
lane list, provision locally, then record the absolute path with
lane-id/branch stale-state preconditions. Never construct a lane from the session checkout.

```text
yoke item-worktrees create PREFIX-N
yoke item-worktrees create PREFIX-N --lane-role worker --branch BRANCH
yoke item-worktrees list PREFIX-N --json
yoke item-worktrees path-record PREFIX-N --worktree-id ID --branch BRANCH --path ABSOLUTE_PATH
```

Evidence-only release requires an allowed post-implementation stage, exactly one
active implementation lane, fixed `evidence-only-recovery` reason and
fresh clean-lane attestation. Verify registered path/branch and absence of
modified tracked or untracked files; ignored-only residue is not dirt. Stale or unverified
evidence fails closed. The refusal names allowed stages.

```text
yoke item-worktrees get PREFIX-N --lane-role implementation --field branch
yoke item-worktrees release PREFIX-N --all-active --reason evidence-only-recovery
```

Merge, landing and close-out keep their pinned workflow/QA/approval boundaries.
For queue projects the PR and combined merge-group head provide admission proof.
Never publish a correction while armed/queued: hold first, verify both queue
entry and merge-when-ready cleared, correct and rerun QA, then re-arm through the
merge boundary. A hold that observes landing returns the actual merge commit.
Pending landing records are durable; clearing one does not fabricate completion.
Release pins retain exact lineage; [deployment contracts](events-and-deployments.md).
