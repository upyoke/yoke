# Onboard Step 5: Declare The Governed Database

Hosting-independent. Entry: confirmed database box. Skip an already
declared model or terminal migration-model-setup answer after live read:

```bash
yoke projects capability-settings get --project {project} --cap-type migration_model --json
```

Populated settings_json: report model slug and skip; absent: use the confirmed
branch. Supported triples:

| authoritative_db.kind | validation_surface.kind | runner.kind |
|---|---|---|
| sqlite_file | worktree_local_sqlite | governed_migration_module |
| postgres | external_validation | governed_migration_module |

Postgres needs existing owning Pulumi stack/output coordinates. Other kinds,
including mysql, are recognized but refused by name: no supported rehearsal runner.
Read [model capabilities](../../../../.yoke/docs/reference/db-reference/migration-model-capabilities.md)
for the exact model/location/provisioning/runner schema before writing.
History directory, connection variable and ledger are project facts, never
borrowed Yoke defaults.

## Declare now

Prepare complete valid JSON from that contract, replacing every project fact.
This SQLite shape illustrates the registered write; use the contract's
Postgres shape for external validation, rather than copying SQLite settings:

```bash
yoke projects capability-settings set --project {project} --cap-type migration_model --new --settings-json '{"default_model":"{slug}","models":{"{slug}":{"authoritative_db":{"kind":"sqlite_file","location":{"path":"{authoritative_path}"}},"validation_surface":{"kind":"worktree_local_sqlite","provisioning":{"path":"{validation_path}","recipe":"{provisioning_recipe}"}},"runner":{"kind":"governed_migration_module","config":{"modules_dir":"{modules_dir}","connection_env_var":"{connection_env_var}","ledger":{"table":"{ledger_table}","entry_column":"{entry_column}","digest_column":"{digest_column}","semantics":"membership","serving_floor_column":"{serving_floor_column}"}}}}}}'
yoke projects capability-settings get --project {project} --cap-type migration_model --json
yoke onboard checklist --run-id {run_id} --row-status migration-model-setup=configured --evidence migration-model-setup="stored model {slug}; authoritative {kind}; runner {runner_kind}; history {modules_dir}; ledger {ledger_table}; readback verified"
```

## Attach later

Coordinates may await step 7. Record known model/kind/history/ledger and the
missing facts; do not write a premature capability:

```bash
yoke onboard checklist --run-id {run_id} --row-status migration-model-setup=deferred --evidence migration-model-setup="planned model {slug}; authoritative {kind}; history {modules_dir}; ledger {ledger_table}; write capability once {missing coordinates} exists"
```

## No Yoke-governed database

No database, externally owned schema, or unsupported authoritative kind is
a complete answer. Every work item keeps its DB claim at `none`; this is the
correct and expected answer, not an omission, because governed mutation binds
a declared model. Nothing further is needed to finish onboarding.

```bash
yoke onboard checklist --run-id {run_id} --row-status migration-model-setup=not-needed --evidence migration-model-setup="no Yoke-governed database: {no DB|schema owner|unsupported kind}; work items keep db_claim state none"
```

## Authorship and failure

Onboard never applies a migration and never rehearses one.
Serving boot converges its database; a migration-authoring item rehearses
against separate validation under configured local authority:

```bash
yoke --env {configured-local-postgres-authority} migration rehearse {ITEM}
```

Read `yoke migration rehearse --help`. It refuses an HTTPS product connection;
that refusal is correct because local migration code is not relayed.

Undecided stops in step 2 at human-interview=blocked. A confirmed model whose
write fails records the validator's exact refusal and satisfying coordinate/
pairing, then stops:

```bash
yoke onboard checklist --run-id {run_id} --row-status migration-model-setup=blocked --blocker migration-model-setup="{validator refusal; required coordinate or supported pairing; recovery}"
```
