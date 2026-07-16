---
name: approve
description: "Approve a deployment stage that is awaiting human approval. Records the approval event via yoke events emit and advances both the run's current_stage and member items' deploy_stage so the pipeline can resume correctly."
argument-hint: "YOK-N [--run <run-id>] [--note \"...\"]"
---

# Internal sub-skill -- called by usher. Not operator-facing.

# /yoke approve YOK-N [--run <run-id>] [--note "..."]

Approve a deployment pipeline stage that is waiting for human approval. Uses the run-based deployment model: advances both the `deployment_runs.current_stage` and each member item's `deploy_stage` to keep the pipeline in sync.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Constants

```
```

## Arguments

- `YOK-N` (required): The backlog item ID.
- `--run <run-id>` (optional): The deployment run ID (e.g., `run-20260317-001`). If omitted, the skill resolves the active run for the item automatically.
- `--note "..."` (optional): A reason or comment for the approval. Recorded in the deployment event envelope.

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. An approval should leave a precise audit trail: what was approved, which run advanced, and why the pipeline may safely continue.

**Error and rollback paths matter here.** Approval changes live deployment state. If preconditions fail or the run cannot advance cleanly, stop with exact diagnostics instead of leaving the operator to reconstruct partial approval state.

## Preconditions

1. **Read deploy_stage and deployment_flow:**

```sh
yoke items get YOK-N deploy_stage
yoke items get YOK-N deployment_flow
```

2. **Gate check and approval via shared mutation contract:** Delegate the entire approval validation, run resolution, and stage advancement computation to the internal approval service path. No registered `yoke` wrapper exists yet. This replaces the previous two-step pattern of `approve-check` + separate DB writes.

```sh
# Internal approval mutation surface; no registered `yoke` wrapper exists yet.
_approval_result=$(python3 -m yoke_core.api.service_client apply-approval {item_num})
```

If the command exits **0**, parse the JSON result for the approval details:
```json
{
 "success": true,
 "next_stage": "prod-deploy",
 "run_id": "run-20260317-001",
 "member_item_ids": [42, 43],
 "approved_at": "2026-03-26T12:00:00Z",
 "field_writes": {"deploy_stage": "prod-deploy", "status": "release", "updated_at": "..."}
}
```

If the command exits **non-zero**, the stage is not approvable. Parse the error from the JSON result and apply these checks before reporting:
 - If deploy_stage is `complete`: print "YOK-N deployment is already complete. Nothing to approve." and **stop**.
 - If deploy_stage ends in `-failed`: print "YOK-N is at stage '{deploy_stage}' (failed), not awaiting approval. Fix the failure and re-run `/yoke usher YOK-N`." and **stop**.
 - Otherwise: print the error from the JSON result and **stop**.

## Approval Flow

1. **The `apply-approval` result already contains the run_id, next_stage, and member_item_ids.** No separate run resolution or member-item queries are needed — the shared mutation layer handles all of that internally.

If `run_id` is null in the result (no active run found and no `--run` provided), print a warning:

```
WARNING: No active deployment run found for YOK-N. Falling back to item-only deploy_stage update.
The pipeline may not resume correctly without a run — verify manually.
```

2. **Record the approval event** via `yoke events emit`:

```sh
yoke events emit \
 --name "DeploymentApprovalGranted" \
 --kind lifecycle \
 --type deployment_run \
 --source-type agent \
 --severity INFO \
 --outcome completed \
 --project "{project}" \
 --context "{\"detail\":{\"run_id\":\"$_run_id\",\"item\":\"YOK-N\",\"flow\":\"$_flow\",\"stage\":\"$_deploy_stage\",\"note\":\"${_note:-approved}\"}}"
```

3. **Apply the stage advancement** using the field_writes, run_id, and member_item_ids from the `apply-approval` result:

**If `run_id` is available (normal path):** Update the run's `current_stage` and all member items' `deploy_stage`:

```sh
# Update run's current_stage
python3 -m yoke_core.cli.db_router runs update "$_run_id" current_stage {next_stage}

# Dual-write: update each member item's deploy_stage
for _item_id in {member_item_ids}; do
 yoke items scalar update "$_item_id" --field deploy_stage --value {next_stage}
done
```

**If `run_id` is null (fallback — item-only):** Update only the item's deploy_stage:

```sh
yoke items scalar update {item_num} --field deploy_stage --value {next_stage}
```

**IMPORTANT:** The `next_stage` value comes directly from the shared mutation layer's approval resolution — it is always a real stage name from the deployment flow (e.g., `prod-deploy`), NOT a synthetic value like `approved`. The pipeline resumes by matching `deploy_stage` against flow stage names — a non-existent name causes all remaining stages to be silently skipped.

4. **Print confirmation:**

> Approval recorded for YOK-N.
> {If run_id available: "Run: {run_id}"}
> Deploy stage advanced to: {next_stage}
>
> {If preview URL was found: "Ephemeral env: {preview_url}"}
> Next step: run `/yoke usher YOK-N` to continue the deployment pipeline.
