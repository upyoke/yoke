---
title: webapp-template-sqlite-default-boundary — audit + classification
decision_type: boundary-audit
status: documented
primary_surfaces:
  - templates/webapp/template.json (migration_model_defaults)
  - templates/webapp/scaffold/app/utils/db.py
  - templates/webapp/scaffold/app/db/schema.sql
  - runtime/api/domain/worktree_validation_recipes.py (webapp_sqlite_empty)
  - runtime/api/domain/migration_model_capability_validation.py (_LIVE_PAIRINGS)
out_of_scope:
  - runtime/api/domain/migration_model_capability_defaults.py (Yoke control-plane seed)
  - templates/webapp/infra/webapp_database_stack.py (opt-in Aurora component)
---

# Webapp template defaults to app-local SQLite — boundary classification

## What this records

The GEN-3 Postgres-native program moved **Yoke's own control plane** from
`data/yoke.db` to Aurora PostgreSQL. A natural follow-on question is whether
the `templates/webapp/**` scaffold — which still ships a SQLite app database —
is GEN-3 SQLite residue that should be converted to Postgres.

It is not. The webapp template's app database is **intentional, first-class,
app-local SQLite**, and this record is the durable home for that boundary so a
future Postgres-cleanup pass does not blind-convert it.

## The two DB layers are different concerns

1. **Yoke's control plane** (the `data/yoke.db` → Aurora migration). This is
   what G3.P1.I7 ("Postgres-native cleanup / SQLite bridge retirement") purges:
   the sqlite3-shaped facade/translator/shims, the SQLite CI lane, backend
   duality, and `data/yoke.db` authority. Yoke-the-project's `migration_model`
   capability declares `authoritative_db.kind=postgres`.

2. **The generated webapp's own application database.** The scaffold is a
   self-contained FastAPI + Next.js + **SQLite** + Docker product. The app reads
   `APP_DB_PATH` (a file path), `utils/db.py` opens it with `sqlite3.connect`,
   `db/schema.sql` is SQLite DDL, and the tests run against a temp SQLite file.
   This is a deliberate zero-ops default for a new product, not a Yoke-runtime
   assumption.

The GEN-3 plan's own acceptance criteria carve this out explicitly: SQLite-token
residue must be empty **"except archived migration docs / one-time import
artifacts / explicit generic SQLite validation surfaces"** (`strategy/GEN-3-PLAN.md`,
G3.P1.I7). The webapp validation surface is precisely such a surface.

## Live evidence (control plane, 2026-06-02)

The two `migration_model` capability rows confirm the split is real and in
production, not a stale default:

| project | `authoritative_db.kind` | `validation_surface` | recipe |
|---|---|---|---|
| `buzz`   | `sqlite_file` | `worktree_local_sqlite` | `webapp_sqlite_empty` |
| `yoke` | `postgres`    | (control-plane)         | — |

Buzz — a real, deployed product webapp — runs the exact template default. The
template SQLite default is therefore the live configuration of a shipping
product. Converting the template default would diverge it from its own primary
consumer.

## The runtime already classifies these surfaces as keep-not-residue

- `runtime/api/domain/worktree_validation_recipes.py` documents the
  `webapp_sqlite_empty` recipe as **"genuine generic-validation SQLite … the
  live recipe for a webapp project (e.g. Buzz) whose own authoritative DB is
  SQLite. Kept regardless of Yoke's Postgres authority; validating external
  SQLite projects is a first-class capability, not residue."**
- `runtime/api/domain/migration_model_capability_validation.py` keeps both
  pairings live and maintained:
  `("sqlite_file", "worktree_local_sqlite", governed_migration_module)` and
  `("postgres", "external_validation", governed_migration_module)`. The SQLite
  pairing is supported, not deprecated-for-removal.

## How a project chooses Postgres (the override path)

A webapp that needs managed Postgres does **not** edit the template default. It
overrides at the project level, the same way Yoke's control plane does:

1. Declare the project `migration_model` capability with
   `authoritative_db.kind=postgres` paired with
   `validation_surface.kind=external_validation` and the
   `governed_migration_module` runner.
2. Compose the opt-in Aurora component `templates/webapp/infra/webapp_database_stack.py`
   into the project's environment stack.
3. Adapt the app layer to a Postgres DSN — `utils/db.py`, `schema.sql`, the
   migration modules, and the tests. This is an app-architecture change, tracked
   as a **Category B** deviation in the project's `DEVIATIONS.md`
   (see `templates/webapp/CUSTOMIZATION.md`).

## Non-goal

This record does not foreclose a future, deliberate product decision to make
Postgres the *template* default. It states only that such a change is a
full app-layer conversion driven by product intent — never an automatic
side effect of the Yoke control-plane GEN-3 cleanup, and never a blind
find-and-replace of `sqlite` → `postgres` across the scaffold.

## Verification at audit time

The named validation suite is the guard for this boundary. This slice tightened
generated scaffold wording and the template description so downstream project
agents see "app-local SQLite" next to the Yoke Postgres-control-plane
boundary; it did not change the migration model defaults, validation recipe, or
runtime app database behavior.

```
runtime/api/domain/test_validate_webapp_pipeline*.py
runtime/api/domain/test_worktree_validation_surface.py
runtime/api/domain/test_projects_validate_commands*.py
=> 49 passed
```
