# Hosted portable migration retirement evidence

Hosted engine migrations use the Platform database as their fleet control
plane. The authoritative retirement evidence is the durable run plus target
receipt stored in `tenant_migration_runs` and `tenant_migration_targets`, not a
tenant-local `migration_audit` row.

This follows the hosted architecture: every tenant database is a physical
target, while Platform owns enumeration, rehearsal, backup, apply, and
coverage. A migration source may retire only when the Stage and Production
runs are `completed` and every target captured by each run is also
`completed`. The fleet lock prevents a tenant from being added between target
enumeration and mutation.

## Retired workflow-registry modules

The following fleet-safe modules completed under the same exact manifest:

- `workflow_file_budget_policy_revision`
- `workflow_item_shape_contract`
- `workflow_item_worktree_records`
- `workflow_item_worktree_source_fields_contract`
- `path_claim_task_bindings`
- `qa_command_plan_cutover`
- `workflow_item_browser_qa_metadata_contract`

Authoritative receipts:

- Stage: `9970d4a1ad7a42a4aaaca6734c769f77`
- Production: `e84704492ed04c22906d039197030d2c`

Both runs and every captured target reached `completed`. Their source modules,
runtime wrappers, standalone manifests, migration-specific tests, and
environment catch-up manifests can therefore retire. Git history and the
Platform receipts preserve the execution record.

## Current installer campaign module

The predecessor-independent `installer_campaign_current_plan` migration also
completed for every captured tenant:

- Stage: `437d060b9e2d4e19b545db00f5727483`
- Production: `3fda85794f3046288e3bb2ec8346f973`

Its migration artifacts can retire independently from the reusable current
installer case definitions that remain product source.

## Evidence boundary

The repository's single-authoritative-database `migration_audit` gate remains
correct for local or project-bound governed migrations. It is not substituted
for the Platform fleet receipt when Platform is the declared hosted portable
migration authority.
