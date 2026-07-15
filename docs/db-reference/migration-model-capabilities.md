# `migration_model` Capability — Python Migration Modules

Per-project declaration of the governed-DB environment. One
`project_capabilities` row per project; `settings.models` is a keyed dict
of model declarations. The `project_capabilities.type` column is the
singular, unsuffixed string `migration_model`.

Yoke core reads this project config at validation-surface provisioning,
rehearsal, and live apply time. The project selects paths and environment
variables; Yoke owns lifecycle gates, leases, freshness checks,
`migration_audit`, rollback evidence, and DB-claim semantics.

## Payload Shape

```jsonc
{
  "default_model": "primary",
  "models": {
    "primary": {
      "authoritative_db": {"kind": "sqlite_file", "location": {...}},
      "validation_surface": {"kind": "worktree_local_sqlite", "provisioning": {...}},
      "runner": {"kind": "governed_migration_module", "config": {...}}
    }
  }
}
```

`default_model`, if present, must name a key inside `models`. Model names
are slug-shape (`^[a-z0-9][a-z0-9_-]*$`). Validator output is normalized
to canonical key order so settings JSON round-trips deterministically.

## Validation Recipes

Recipes are responsible for a project-local **validation surface**. They create
the validation target and the minimal scaffolding the configured Python
migration module can apply against. A recipe never applies a migration module.
Yoke's own Postgres-authority model uses `external_validation` and does not
use a local SQLite recipe.

| Recipe | Behavior |
|---     |---       |
| `webapp_sqlite_empty` | Webapp behavior: creates the SQLite file, sets the canonical PRAGMA tuple on the seeding connection, and creates an empty `schema_version` table. Python migration modules own schema changes. |

Unknown recipes raise
`yoke_core.domain.worktree_validation_recipes.UnknownValidationRecipe`
at dispatch time and a `MigrationModelCapabilityError` at validation
time. Both messages carry the project, model, and configured recipe.

## Runner

The configured runner kind is `governed_migration_module`: a Python file
named `<identifier>.py` under `runner.config.modules_dir` with a callable
`apply(conn)` surface and an optional `invariants(conn)` hook.

Config keys:

| Key | Meaning |
|---  |---      |
| `modules_dir` | Project-relative directory containing Python migration modules. |
| `connection_env_var` | Env var implementation/test code should bind to the validation or authoritative DB target. Defaults to `YOKE_PG_DSN` when omitted. |

`migration_audit.module_identifier` is the bare module slug from
`db_mutation_profile.migration_modules`, without path or `.py` suffix.
Rehearsal and live apply dispatch the same slug through the same runner
shape; only the checkout root differs (`worktree_path` during rehearsal,
this machine's registered project checkout during live apply).

### Ticketless committed manifests

Operator-directed maintenance that deliberately has no backlog item uses a
committed migration manifest instead of synthesizing a ticket. The manifest
contains the same validated `db_mutation_profile` and
`db_compatibility_attestation` the item-backed path reads, plus `version: 1`
and the project slug. Every authored attestation field must be non-empty.

Both units require an explicit clean worktree attached to the project's
registered checkout. The manifest and every named module must be tracked at
HEAD and must not be symlinks. Rehearsal records the full source commit,
manifest-relative path, and manifest SHA-256 in
`migration_audit.description`; live apply refuses unless those values match
exactly, then revalidates the clean pinned checkout immediately before loading
each module after the backup window. The ordinary fingerprint, freshness,
lease, backup, baseline verification, module invariant, and audit state
machinery otherwise runs unchanged. The itemless path never auto-deletes a
module; source cleanup follows authoritative apply evidence.

For the `external_validation` model, create a separate empty Postgres database,
set only `YOKE_PG_DSN_VALIDATION` to that target, and hydrate it from the
selected authority before rehearsal:

```bash
python3 -m runtime.api.tools.authority_validation_copy
```

The helper refuses an authority/validation identity match, does not print
credentials, and replaces the validation database contents with a
no-owner/no-privileges dump restore. Merely creating an empty validation
database is insufficient because migration modules rehearse against the
deployed schema and data shape.

```bash
python3 -m yoke_core.domain.migration_apply rehearse-manifest \
  runtime/api/domain/migrations/<name>.migration.json \
  --worktree-path /absolute/path/to/clean/worktree

python3 -m yoke_core.domain.migration_apply live-apply-manifest \
  runtime/api/domain/migrations/<name>.migration.json \
  --worktree-path /absolute/path/to/the-same-clean-worktree
```

These remain separate invocations, preserving the operator checkpoint. A
dirty checkout, untracked or symlinked source, checkout-authority mismatch,
changed commit or manifest digest, stale database fingerprint, held lease, or
failed backup refuses before destructive SQL.

### Hosted engine fleet executors

An installed engine fleet has one platform control plane and many physical
tenant targets. It must not pretend that each target is a standalone Yoke
install or put fleet receipts on a tenant database. The public wheel therefore
provides
[`yoke_core.domain.portable_migration`](../../packages/yoke-core/src/yoke_core/domain/portable_migration.py),
which validates the same manifest theorem and loads migration implementations
from `yoke_core.domain.migrations`. The source-checkout wrapper and installed
fleet executor import that one packaged implementation.

The portable surface deliberately resolves no DSN, project row, lease, backup
path, or audit table. A fleet executor owns those concerns in its separate
control plane and must preserve the governed runner's ordering for every
physical target:

1. Prove the exact installed engine pin and complete reader/writer rollout.
2. Enumerate registry targets and physical databases, refusing any difference.
3. Rehearse the exact raw manifest and packaged module on isolated restored
   copies, recording source fingerprints and invariant results.
4. Stop for a separate operator checkpoint with bounded freshness.
5. Recheck pin, coverage, and fingerprints; durably receipt a rollback backup
   for each target before calling `apply_manifest`.
6. Record each target result in the fleet control plane and require explicit
   recovery authority after a failed or unexpected partial state.

`apply_manifest` keeps the public runner's module-apply, commit, fixed baseline,
optional author-invariant, and affected-table-count order. It is not an
alternate command that weakens the
ordinary stage/prod path: those governed units still run their manifest source
rehearsal, lease, backup, fingerprint, and `migration_audit` machinery.

A packaged migration remains in the wheel until completed evidence exists for
every install that can still carry the old schema: ordinary authoritative
stage/prod databases and every physical hosted tenant. Validation-copy success
alone is never retirement evidence.

## `migration_audit` Bootstrap

Audit rows live on the **model's authoritative DB**, not the
Yoke control plane. For Yoke-as-project the authoritative DB and the
control plane DB coincide, so [`create_governed_tables`](../../runtime/api/domain/schema_init_tables.py)
covers `migration_audit` at control-plane init. For non-Yoke projects
(e.g. Buzz with `authoritative_db.location.path = "app/data/app.db"`)
the two diverge.

[`yoke_core.domain.migration_audit_schema.ensure_migration_audit_table(conn)`](../../runtime/api/domain/migration_audit_schema.py)
is the canonical idempotent helper. Both
[`migration_apply_rehearse._rehearse_inner`](../../runtime/api/domain/migration_apply_rehearse.py)
and
[`migration_apply_live._live_apply_inner`](../../runtime/api/domain/migration_apply_live.py)
call it on `audit_conn` immediately after opening, so a webapp project's
first governed apply bootstraps the table automatically. Operators and
agents do not declare or provision `migration_audit` themselves; the
project capability only names the authoritative DB. `coordination_leases`
stays Yoke-side (`LIVE_DB_MIGRATION:<model_name>` leases live on the
control plane), so the helper deliberately does not bootstrap it on
project authoritative DBs.

## Pairing Matrix

The wired pairings are:

| `authoritative_db.kind` | `validation_surface.kind` | `runner.kind` |
|---                      |---                         |---            |
| `sqlite_file`           | `worktree_local_sqlite`   | `governed_migration_module` |
| `postgres`              | `external_validation`     | `governed_migration_module` |

The SQLite pairing is project-generic: webapp projects use it with
project-local module paths and the app DB env var. The Postgres pairing is
Yoke's authority shape — `authoritative_db.kind="postgres"` with
`modules_dir="runtime/api/domain/migrations"` and the `YOKE_PG_DSN`
runner binding. Validation is external to this worktree-local provisioning
surface; the authoritative DB location names a Postgres stack/output source:

```json
{
  "kind": "postgres",
  "location": {
    "stack": "<production-stack>",
    "state_backend": "<capability-resolved-state-backend>",
    "region": "<aws-region>",
    "database_name": "<database-name>",
    "endpoint_output": "databaseClusterEndpoint",
    "secret_arn_output": "databaseSecretArn"
  }
}
```

The validator keeps this shape generic: it validates stack/output/database
references, not Yoke-only endpoint literals. Local proof commands can bind the
resolved DSN via `YOKE_PG_DSN_FILE` so secret-bearing DSNs stay in a
restricted file instead of shell-expanded arguments. The polished connected-env
switch UX remains a later cloud-runtime capability; this pairing only declares where
authority lives after cutover. Other runner kinds are schema-reserved and
rejected.

## Webapp Template + Buzz Seed

The webapp template's [`templates/webapp/template.json`](../../templates/webapp/template.json)
carries a top-level `migration_model_defaults` block describing what a
rendered webapp project should declare:

```json
{
  "migration_model_defaults": {
    "default_model": "primary",
    "models": {
      "primary": {
        "authoritative_db": {
          "kind": "sqlite_file",
          "location": {"path": "app/data/app.db"}
        },
        "validation_surface": {
          "kind": "worktree_local_sqlite",
          "provisioning": {
            "path": ".yoke/validation.db",
            "recipe": "webapp_sqlite_empty"
          }
        },
        "runner": {
          "kind": "governed_migration_module",
          "config": {
            "modules_dir": "app/db/migrations",
            "connection_env_var": "APP_DB_PATH"
          }
        }
      }
    }
  }
}
```

Webapp projects declare their `migration_model` capability from that
template block at onboarding time; a fresh universe seeds no per-project
capability rows. Future webapp projects inherit the same Python
migration-module capability shape without copy-paste-with-variation.

This SQLite pairing is only for the generated app's app-local product database
and its worktree-local rehearsal DB. It is not a Yoke authority
recommendation: Yoke's own Postgres control plane uses the pairing above, and
project-local webapp agents must not infer a Yoke `data/yoke.db` from these
defaults.

## DB-Claim Semantics

This page describes capability configuration, not a governed mutation.
A ticket that adds, edits, or removes a `migration_model` settings JSON
on the Yoke control-plane DB is doing project-capability work; the
default `db_mutation_profile.state="none"` claim covers it. If
implementation discovers an unexpected `ALTER TABLE` or
`INSERT INTO <governed table>` mutation beyond `project_capabilities`,
dispatch `db_claim.amend` before advancing (see
[`AGENTS.md` § Governed DB Mutation](../../AGENTS.md)).
