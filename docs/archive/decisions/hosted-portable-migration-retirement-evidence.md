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

## Retired workflow and QA convergence modules

The final workflow-registry, QA execution, hosted-environment, generated-task,
and event-identity convergence completed for every hosted database before its
source retired:

- `workflow_supporting_schema_records`
- `qa_requirement_execution_snapshot`
- `qa_plan_execution_records`
- `qa_plan_execution_deployment_subject`
- `qa_hosted_runtime_environment`
- `qa_execution_environment_target`
- `qa_plan_agent_review_records`
- `epic_task_scope_state`
- `events_actor_identity`

Authoritative evidence:

- Stage control-plane authority `yoke_tenant_1`: all nine modules completed
  under migration lease `73`.
- Stage fleet run `4aa5fcf64e1e4999b75a3f8216c0a075`: both captured
  tenants completed; rehearsal workflow `30503287080` and apply workflow
  `30503334782`.
- Production control-plane authority `yoke_tenant_4`: all nine modules
  completed under migration lease `736` after a fresh Production-copy
  rehearsal.
- Production fleet run `ddcd9e5820994691bf4313fc03cd9448`: tenants `4`, `34`,
  `67`, `100`, `133`, `166`, and `199` completed; rehearsal workflow
  `30554793256` and apply workflow `30555707543`.

The durable execution-subject convergence required by normal startup moved to
the permanent QA plan execution schema authority before the migration wrapper
retired. The nine package modules, runtime wrappers, standalone and combined
manifests, and migration-only tests can therefore be removed without removing
current schema behavior or its regression coverage.

## Evidence boundary

The repository's single-authoritative-database `migration_audit` gate remains
correct for local or project-bound governed migrations. It is not substituted
for the Platform fleet receipt when Platform is the declared hosted portable
migration authority.
