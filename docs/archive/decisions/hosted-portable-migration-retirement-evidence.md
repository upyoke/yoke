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
environment catch-up manifests can therefore retire. Migration-only worktree
source discovery, backfill, and dormant-plan deferral helpers also retire
because they have no live callers after those modules are removed. Git history
and the Platform receipts preserve the execution record.

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

## Retired public-reference repair module

`item_dependency_public_ref_repair` completed on every authority it targeted:

- Stage control plane: completed from source
  `07e2bdfea651568338861209ef0de3f619702b6e` at
  `2026-07-30T20:12:33Z`.
- Stage fleet run `10ad304e829546c29f7a2f637f9449b8`: every captured target
  completed; apply workflow `30598867683` succeeded.
- Production control plane: completed from the same source at
  `2026-07-30T19:49:05Z`.
- Production fleet run `a6893856f6dc42db9c0898c8106ad811`: the sanctioned
  Platform reader proved that every captured target completed. Workflow
  `30600019593` reported failure only because the former workflow parser
  rejected stdout preceding the terminal JSON receipt.

The workflow now validates the terminal receipt line, while the durable fleet
run and target rows remain the authority. The package module, runtime wrapper,
manifest, and migration-specific test can therefore retire.

## Evidence boundary

The repository's single-authoritative-database `migration_audit` gate remains
correct for local or project-bound governed migrations. It is not substituted
for the Platform fleet receipt when Platform is the declared hosted portable
migration authority.

## Retired session identity and policy capability modules

`harness_session_project_identity` and `project_policy_capabilities` completed
under corrected source `110eb483abd0fd84df4c6a6ee8ec3010bbdd8647`:

- Stage control plane lease `109`: session identity completed at
  `2026-08-01T17:55:11Z`; policy capabilities completed at
  `2026-08-01T17:55:25Z`.
- Stage fleet run `8dba656375dd4760be29d4a9239190c5`: tenants `1` and `2`
  completed; rehearsal workflow `30711382666` and apply workflow
  `30711419999` succeeded.
- Production control plane lease `1132`: session identity completed at
  `2026-08-01T18:05:06Z`; policy capabilities completed at
  `2026-08-01T18:07:55Z`.
- Production fleet run `9d416dd385be4f8887053343390da42e`: tenants `4` and
  `166` completed; rehearsal workflow `30711847608` and apply workflow
  `30711999749` succeeded.

Tenant `166` contained no project named `yoke` and therefore proved that the
corrected migration is reusable for external projects: it binds sessions to
the tenant's own primary project identity rather than to a product slug or a
fixed numeric id.

The failed predecessor rehearsal `b13fd3976fb542f4913b9bcb6802a2f1` retained
one diagnostic Production validation clone. After the corrected run completed,
governed disposal workflow `30712150503` removed that exact clone. Stage
inventory workflow `30712089369` and Production inventory workflow
`30712174112` both reported zero validation databases afterward.

The package modules, runtime wrappers, combined manifest, and migration-specific
tests can therefore retire. The permanent project-policy implementation and
the generic portable-migration executor and tests remain product source.

The permanent installer campaign interaction regression and its assertion
helper are product tests, not migration source. They live under
`runtime/api/domain/` after the campaign migration retires so the governed
modules directory contains no campaign-named test residue.
