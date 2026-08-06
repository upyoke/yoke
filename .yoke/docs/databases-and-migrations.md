# Databases and migrations

Workbench path: **Delivery → Databases**.

## What you see

Declared database / migration models, compatibility posture, and apply
records for the project's governed mutation story.

## Operator model

- Pure **additive** schema (new tables/columns) converges on boot — no
  special migration module required for net-new additive shape.
- **Data-transforming** changes (drops, backfills, rewrites) go through the
  ordered migration history, rehearsal, and boot apply.
- Every item carries a **DB claim** (`db_claim.amend`). Default `none` means
  no governed mutation declared.

## Authoring posture

When an item mutates a declared authoritative DB:

1. Amend the DB claim (profile + compatibility attestation as required)
2. Author the migration module in history
3. `yoke migration rehearse PREFIX-N` from a local-postgres / db-admin
   connection (holds the live migration lease)
4. Ship; boot converge applies pending entries fail-hard

Never apply destructive migrations without a named restore point. Never use
ad hoc write SQL against a declared authoritative DB.

## Item vs fleet

Rehearsal against the validation surface does not prove every tenant DB.
Fleet preflight exists for release trains that carry unapplied history.

Deep reference: [reference/db-reference.md](reference/db-reference.md) and
`reference/db-reference/migration-model-capabilities.md`.
