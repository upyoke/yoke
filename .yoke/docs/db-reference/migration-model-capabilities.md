# `migration_model` Capability — Python Migration Modules

Per-project declaration of the governed-DB environment. One
`project_capabilities` row per project; `settings.models` is a keyed dict
of model declarations. The `project_capabilities.type` column is the
singular, unsuffixed string `migration_model`.

Yoke core reads this project config at validation-surface provisioning,
rehearsal, and apply time. The project selects paths and environment
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
| `connection_env_var` | Required project-owned env var that implementation/test code binds to the validation or authoritative DB target. Generic validation never substitutes Yoke authority. |
| `artifact_version_env_var` | Optional env var naming the running artifact version. Doctor uses it to compare recorded serving floors when an older packaged history sees newer ledger rows; without it that rollback check reports limited evidence, never a false mismatch. |
| `ledger` | Required. Names where applied membership, raw-byte identity, and serving floors are recorded. |

### Ledger (content-identity and rollback-safety contract)

Every governed model declares `ledger`; an omitted or partial declaration
cannot answer whether the database is current or safe for this build and is
therefore refused:

| Key | Meaning |
|---  |---      |
| `table` | Ledger table that records applied entries. |
| `entry_column` | Column holding each entry's identity (membership key). |
| `digest_column` | Nullable column holding SHA256 of the exact migration-module bytes. New declarations emit it explicitly. Stored declarations from before content identity normalize an omission to the project-neutral `content_sha256` standard. |
| `semantics` | Must be `membership`. Threshold / high-water marks are refused. |
| `serving_floor_column` | Column holding the oldest build that may serve after a destructive entry. Required — membership alone cannot stop a rolled-back build from serving a database it cannot read. |
| `applied_at_column` | Optional applied timestamp identifier; normalized to `applied_at` when omitted. |
| `applied_by_column` | Optional applying-actor identifier; normalized to `applied_by` when omitted. |

```json
"ledger": {
  "table": "applied_migrations",
  "entry_column": "migration_name",
  "digest_column": "content_sha256",
  "semantics": "membership",
  "serving_floor_column": "minimum_serving_version",
  "applied_at_column": "applied_at",
  "applied_by_column": "applied_by"
}
```

Boot must answer three questions before serving: (1) is the pending set empty?
(2) does every non-NULL digest shared by ledger and packaged history match the
raw packaged bytes? (3) is any applied floor newer than this build? A non-NULL
digest mismatch is fatal before the current fast path, restore-point creation,
or mutation. A legacy NULL is reported as `adoption_required`, not silently
filled and not treated as a boot mismatch. Per new applied entry the ledger
records membership, raw-byte SHA256, and the declared serving floor in the
same transaction. Decision records:
[`project-migration-ledger-contract.md`](../../../docs/archive/decisions/project-migration-ledger-contract.md)
(membership vs threshold) and
[`project-migration-rollback-safety.md`](../../../docs/archive/decisions/project-migration-rollback-safety.md)
(why the floor is required). `HC-project-migration-ledger-contract` reports
whether a declaring project satisfies the contract; unreadable is a finding,
never a PASS.

An older artifact normally sees applied entry names absent from its packaged
history. That is rollback, not a project/history mismatch: membership still
answers whether everything the older artifact ships has run. Serving safety is
decided from those newer rows' recorded floors. When Doctor has no running
artifact version (no declared/bound `artifact_version_env_var`), it reports
that comparison as limited evidence instead of failing the names themselves.

`migration_audit.module_identifier` is the bare module slug from
`db_mutation_profile.migration_modules`, without path or `.py` suffix.
Rehearsal dispatches the slug through the runner against the model's
validation surface, rooted at `worktree_path`.

For Yoke's `external_validation` model, create a separate empty Postgres
database, set only `YOKE_PG_DSN_VALIDATION` to that target, and hydrate it from
the selected authority before rehearsal. Other projects use their explicitly
declared `<connection_env_var>_VALIDATION`; the generic runner supplies no
Yoke-named default:

```bash
# Yoke source repo only — an in-tree helper, not importable from an installed
# Yoke. Other projects hydrate the validation database their own way.
python3 -m runtime.api.tools.authority_validation_copy  # Yoke source repo only
```

The helper refuses an authority/validation identity match, does not print
credentials, and replaces the validation database contents with a
no-owner/no-privileges dump restore. Merely creating an empty validation
database is insufficient because migration modules rehearse against the
deployed schema and data shape.

`<modules_dir>` is the value the project's declared `migration_model`
capability payload carries under `runner.config.modules_dir` — read it there,
never from another project's layout. It holds the model's **ordered migration
history**: `NNNN_slug.py` entries, permanent, each exposing `apply(conn)` and
optionally `invariants(conn)`.

```bash
python3 -m yoke_core.domain.migration_apply rehearse PREFIX-N
```

Rehearsal runs the declared entries against the validation surface and records
the receipt the evidence gate reads. There is no second invocation and no
operator checkpoint to hold, because rehearsal is the only thing a work item
performs: the apply happens on the boot converge of a server running the merged
code.

### Hosted engine fleet

An installed engine fleet has one platform control plane and many physical
tenant targets, and needs no fleet executor at all. Each tenant container
applies its own pending set at boot from the history packaged in the wheel it
runs, so the ordinary fleet roll — stop, start, health-gate — IS the apply
mechanism for every target. The roll's per-tenant health gate asserts
`migrations_current`, so a tenant that could not apply fails its gate and halts
the roll rather than serving behind its schema.

The wheel is the distribution mechanism and pip/image digests are the integrity
boundary. Every release also publishes deterministic `migration-history.json`
and independently attestable `migration-history-record.json`. The record binds
the manifest SHA256, exact core-wheel SHA256, engine version, and full source
commit; the mutable channel repeats the manifest SHA256 and source commit.
Release validation refuses drift among those surfaces, and GitHub attests the
wheel, manifest, and record to the same source commit. There is still no
per-target migration dispatch: each tenant boot applies its own pending set.

### Legacy digest adoption and pre-deploy ordering

Adoption is an explicit state-equivalence claim, not a backfill. The selected
artifact manifest must exactly match the selected packaged history and its
independently trusted manifest digest/source commit. Before any ledger UPDATE,
every selected entry must pass a project-owned verifier from the optional
registry/resolver, or its callable `invariants(conn)` fallback when no registry
is supplied. A supplied registry fails closed on unknown or non-callable
entries. Every verifier runs inside a rolled-back savepoint. The adopter then
updates only NULL digest rows and appends artifact, manifest, actor, and time
evidence in one transaction; a conflict or invariant failure leaves both
ledger and evidence unchanged.

For Platform Stage/production, ordering is mandatory:

1. From the candidate package, a Platform admin adapter calls
   `prepare_migration_content_schema(conn, platform_ledger,
   platform_evidence_contract)`. It commits nullable metadata, the evidence
   table, and database-enforced append-only guards as a distinct transaction,
   so the deployed build remains compatible.
2. The adapter loads a Platform-source manifest and externally trusted manifest
   SHA/source commit, selects Platform's own permanent history, and calls the
   generic `adopt_legacy_content_identities`, binding both
   `adoption_evidence_writer(platform_evidence_contract)` and
   `adoption_evidence_verifier(platform_evidence_contract)`. It then requires
   no common-row mismatch or remaining adoptable NULL.
3. Only after that receipt is durable may the candidate Platform build boot.

Yoke tenant fleets use the installed wrapper, which selects all tenant DBs from
the named admin environment unless explicit DB names are supplied:

```bash
python3 -m yoke_core.tools.adopt_migration_content_identity stage-db-admin \
  --wheel <attested-yoke-core-wheel> \
  --manifest <attested-migration-history.json> \
  --release-evidence <attested-migration-history-record.json> \
  --source-commit <full-commit> --manifest-sha256 <sha256> \
  --adopted-by operator:<name> --prepare
```

The mandatory `--prepare` invocation commits only additive schema. After it
succeeds on the whole selected fleet, repeat the same command without a mode
for invariant verification and a printed plan; then repeat with `--apply` for
atomic adoption. The tool refuses verify/apply when preparation or its
immutability guards are absent. Platform and external projects call the generic
primitives with their own history, ledger, evidence table, and artifact type;
they do not reuse Yoke tenant enumeration or wheel assumptions.

Full-universe replacement is the only sanctioned guard suspension. Trusted
schema bootstrap truncation transactionally disables only Yoke-owned
BEFORE-TRUNCATE adoption-evidence guards, leaves UPDATE/DELETE guards active,
and re-enables the truncate guards before commit. Ordinary writes and direct
TRUNCATE remain denied. Readiness checks verify enabled state, exact event and
row/statement coverage, the owning function, and its append-only body rather
than trusting object names alone.

## `migration_audit` Bootstrap

Audit rows live on the **model's authoritative DB**, not the
Yoke control plane. For Yoke-as-project the authoritative DB and the
control plane DB coincide, so `yoke_core.domain.schema_init_tables.create_governed_tables`
covers `migration_audit` at control-plane init. For non-Yoke projects
(e.g. a webapp with `authoritative_db.location.path = "app/data/app.db"`)
the two diverge.

`yoke_core.domain.migration_audit_schema.ensure_migration_audit_table(conn)`
is the canonical idempotent helper. Both
`yoke_core.domain.migration_apply_rehearse._rehearse_inner`
and
`yoke_core.domain.migration_boot_apply.apply_pending`
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

Four vocabulary values are deliberately recognized but rejected until their
complete pairing exists: authoritative DB `mysql`, validation surfaces
`staging_db` and `ephemeral_container`, and runner `external_adapter`. They are
not implied live pairings and must remain visible as explicit refusals.

The SQLite pairing is project-generic: webapp projects use it with
project-local module paths and the app DB env var. The Postgres pairing is
Yoke's authority shape — `authoritative_db.kind="postgres"` with the
`runner.config.modules_dir` from its own capability payload and the
`YOKE_PG_DSN` runner binding. Validation is external to this worktree-local
provisioning surface; the authoritative DB location names a Postgres
stack/output source:

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

## Webapp Pack Configuration

The Webapp Scaffold Pack's
[`settings-reference.json`](../../packs/webapp-scaffold/versions/1.1.2/settings-reference.json)
carries a top-level `migration_model_defaults` block describing what an
installed webapp project can declare:

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
            "connection_env_var": "APP_DB_PATH",
            "ledger": {
              "table": "applied_migrations",
              "entry_column": "migration_name",
              "digest_column": "content_sha256",
              "semantics": "membership",
              "serving_floor_column": "minimum_serving_version"
            }
          }
        }
      }
    }
  }
}
```

Webapp projects may declare their `migration_model` capability from that Pack
reference during onboarding; a fresh universe seeds no per-project capability
rows. The Pack provides a reusable starting shape without making the installed
project source centrally managed.

This SQLite pairing is only for the generated app's app-local product database
and its worktree-local rehearsal DB. It is not a Yoke authority
recommendation: Yoke's own Postgres control plane uses the pairing above, and
project-local webapp agents must not infer a Yoke `data/yoke.db` from these
defaults.

## DB-Claim Semantics

This page describes capability configuration, not a governed mutation.
A work item that adds, edits, or removes a `migration_model` settings JSON
on the Yoke control-plane DB is doing project-capability work; the
default `db_mutation_profile.state="none"` claim covers it. If
implementation discovers an unexpected `ALTER TABLE` or
`INSERT INTO <governed table>` mutation beyond `project_capabilities`,
dispatch `db_claim.amend` before advancing (see
[`AGENTS.md` § Governed DB Mutation](../../AGENTS.md)).
