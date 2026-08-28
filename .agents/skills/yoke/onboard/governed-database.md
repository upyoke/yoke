# Onboard Step 5: Declare The Governed Database

The governed-database half of step 5, a sibling of
[verification-binding.md](verification-binding.md). Like the verification
binding it is independent of the hosting branch: a project with no managed
host still answers this question, and "no governed database" is a complete
answer rather than a skipped step.

- **Entry:** the step-2 profile confirmed one of the governed-database box's
  outcomes.
- **Skip:** the project already declares a `migration_model` capability, or
  this run's `migration-model-setup` row already carries a terminal status.
- **Row:** `migration-model-setup`.

## Read the live state first

```bash
yoke projects capability-settings get --project {project} --cap-type migration_model --json
```

A populated `settings_json` means the project already declared its model:
report the model slug and skip. An absent capability means the question is
open, and the confirmed box says which branch below applies.

## Supported pairings

A model declares three things that must agree: the authoritative database, the
separate validation surface migration code actually runs against, and the
runner that applies entries. Two combinations are supported:

| `authoritative_db.kind` | `validation_surface.kind` | `runner.kind` |
|---|---|---|
| `sqlite_file` | `worktree_local_sqlite` | `governed_migration_module` |
| `postgres` | `external_validation` | `governed_migration_module` |

A `postgres` location names the Pulumi stack that owns the cluster plus the
stack outputs the runner resolves it through, so it cannot be written before
that stack exists. Any other authoritative kind — `mysql` included — is
recognized by the validator and refused by name, because Yoke has no runner
for it. Refusing is the honest outcome: a declared model that cannot rehearse
is worse than a recorded "Yoke does not govern this database".

## Branch 1: declare the model now

Write the capability, then read it back to confirm what was stored:

```bash
yoke projects capability-settings set --project {project} --cap-type migration_model \
  --new --settings-json '{"default_model":"{slug}","models":{"{slug}":{"authoritative_db":{...},"validation_surface":{...},"runner":{...}}}}'
```

The runner config names the ordered-history directory, the connection
environment variable the project's own code reads, and the ledger table each
database records its applied entries in. Those are project facts; there is no
Yoke default to inherit, and a seed that inherited one would validate while
pointing at the wrong code.

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status migration-model-setup=configured \
  --evidence migration-model-setup="migration_model declared: model {slug}; authoritative {kind}; runner {runner_kind}; history {modules_dir}; ledger {ledger_table}"
```

## Branch 2: name the model, attach it later

The project will have a governed database, but its coordinates do not exist
yet — commonly a Pulumi stack step 7 has not applied. Record what is known and
what is missing, so the next agent to reach a schema-mutating work item reads
a decision instead of a silence:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status migration-model-setup=deferred \
  --evidence migration-model-setup="governed model {slug} planned: authoritative {kind}; history {modules_dir}; ledger {ledger_table}; capability written once {what is missing} exists"
```

## Branch 3: no Yoke-governed database

Say this outcome out loud rather than leaving the step blank. It covers three
real projects: one with no database at all, one whose database exists but
whose schema changes someone else owns (a vendor product, a DBA-owned change
process), and one whose authoritative kind has no supported pairing above.

Tell the operator what follows from it: the governed-mutation contract applies
to a project that declares a model, so with none declared every work item
keeps its DB claim at `none`, and that is the correct and expected answer, not
an omission. Nothing further is needed to finish onboarding.

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status migration-model-setup=not-needed \
  --evidence migration-model-setup="no Yoke-governed database: {no database at all|schema owned by {who}|authoritative kind {kind} has no supported runner}; work items keep db_claim state none"
```

## Rehearsal is authorship, not an onboard apply

Onboard never applies a migration and never rehearses one. Applying is the
server's own job at boot: it converges its database to the code it is running
before it serves. Rehearsal belongs to a work item that authors a migration
entry, and validates it against the model's separate validation database:

```bash
yoke --env {local-postgres-or-db-admin-connection} migration rehearse {ITEM}
```

Run `yoke migration rehearse --help` for the full binding order and recovery.
The command refuses an HTTPS product connection because project-local
migration code is not relayed — that refusal is correct, and neither this step
nor anything it writes changes it.

## Failure floor

An undecided governed-database box never reaches this step; the step-2
confirmation records `human-interview=blocked` instead. If the box was
confirmed but the capability write fails here, record the refusal verbatim and
stop:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status migration-model-setup=blocked \
  --blocker migration-model-setup="{the validator's refusal, plus the coordinate or pairing that would satisfy it}"
```
