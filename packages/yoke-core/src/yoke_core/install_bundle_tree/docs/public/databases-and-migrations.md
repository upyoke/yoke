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

A module's optional `invariants(conn)` hook is a permanent claim, not a
post-apply snapshot. It re-runs on every fleet preflight against a copy of a
live database, so it may assert only what the entry owes forever — the schema
shape it produced, or a data fact no live writer can undo. Asserting the row
state the apply happened to leave behind fails from the first legitimate write
onward and blocks the release train. Correcting a mis-stated invariant is
always a new history entry declaring `RETIRES_INVARIANTS`: an applied entry's
bytes are recorded in every ledger that ran it, so editing the module in place
makes those databases refuse to boot on a content mismatch.

## Item vs fleet

Rehearsal against the validation surface does not prove every tenant DB.
Fleet preflight exists for release trains that carry unapplied history or a
schema-shape change no current receipt covers; after converging each
throwaway copy of a live database it also re-runs callable invariants for
every shipped entry that already has ledger membership so a green membership
row cannot hide a historical verification failure. The pre-tag release gate
refuses unless both the history names and this build's schema-shape digest
are covered for the target environment.

Deep reference: [reference/db-reference.md](reference/db-reference.md) and
`reference/db-reference/migration-model-capabilities.md`.
