# Migration model audit and pairing

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Databases](index.md) > Migration pairing
<!-- /yoke:breadcrumbs -->

Configure migration audit bootstrap, environment pairing and the Webapp Pack against the migration model contract.

## `migration_audit` Bootstrap

`migration_audit` carries two kinds of row in two places. **Rehearsal
receipts are item evidence** and live on the control plane that holds the
item, keyed by `project_id` and `model_name`:
`yoke_core.domain.migration_rehearsal_evidence` owns that location for the
rehearsal that writes them and the evidence gate that reads them, so a project
whose authority is a database the control plane cannot open is gated the same
way as Yoke itself. **Boot-apply rows** live on the database being converged,
written by `yoke_core.domain.migration_boot_apply.apply_pending` beside the
ledger row they describe.

`yoke_core.domain.migration_audit_schema.ensure_migration_audit_table(conn)`
(and its Postgres sibling) is the canonical idempotent helper; both writers
call it before their first row, so operators and agents never provision
`migration_audit` themselves. The migration-territory claim stays on the
control plane too (`LIVE_DB_MIGRATION:<model_name>`).

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

The validator keeps this shape generic: it validates stack/output/database
references, not Yoke-only endpoint literals.
Local proof commands can bind the
resolved DSN via `YOKE_PG_DSN_FILE` so secret-bearing DSNs stay in a
restricted file instead of shell-expanded arguments. This pairing declares
authority and validation bindings; other runner kinds are schema-reserved and
rejected. The SQLite `migration_model_defaults` payload appears below under
[Webapp Pack Configuration](#webapp-pack-configuration).

## Webapp Pack Configuration

The Webapp Scaffold Pack's app database is **app-local SQLite**. Yoke backlog
and delivery state stay on the **Postgres control plane** — never aim Yoke
operations at the app DB or the retired worktree-local `data/yoke.db` path.
The pack's `packs/webapp-scaffold/versions/1.1.2/settings-reference.json`
(Yoke source tree) carries a top-level `migration_model_defaults` block:

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

## Related

- [Migration model](migration-model.md)
