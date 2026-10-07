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
3. Rehearse from the configured local-Postgres authority that owns the item
   with `yoke --env <name> migration rehearse PREFIX-N` (holds the live
   migration lease). If none is configured, escalate to the control-plane
   operator; rehearsal executes project-local code and is not relayed over HTTPS.
4. Ship; boot converge applies pending entries fail-hard

Never apply destructive migrations without a named restore point. Never use
ad hoc write SQL against a declared authoritative DB.

## Migration invariants

A module's optional `invariants(conn)` hook is a permanent claim, not a
post-apply snapshot. It re-runs on every fleet preflight against a copy of a
live database, so it may assert only what the entry owes forever — the schema
shape it produced, or a data fact no live writer can undo. Asserting the row
state the apply happened to leave behind fails from the first legitimate write
onward and blocks the release train. It must also hold after this entry's own
`apply(conn)`, since rehearsal runs the entry alone against a validation
surface that may predate everything before it — assert only a shape this entry
establishes. Correcting a mis-stated invariant is
always a new history entry declaring `RETIRES_INVARIANTS`: an applied entry's
bytes are recorded in every ledger that ran it, so editing the module in place
makes those databases refuse to boot on a content mismatch.

## Item vs fleet

Rehearsal against the validation surface does not prove every live database.
Each migration model declares its `fleet` — the engine's tenant databases,
databases the project names and converges with its own boot command, or
`none` with a reason — and `yoke watch preflight -- --project P <environment>`
rehearses exactly that fleet for every project
([reference/db-reference/migration-model-fleet.md](reference/db-reference/migration-model-fleet.md)).
Fleet preflight exists for release trains carrying a history entry or a
schema shape no current receipt covers for the target environment; after converging each
throwaway copy of a live database it also re-runs callable invariants for
every shipped entry that already has ledger membership so a green membership
row cannot hide a historical verification failure. A passing run records what
it covered on the rehearsed environment's own settings document, so coverage
is durable state rather than telemetry that can expire out from under a build
that was already rehearsed. The pre-tag release gate refuses unless both the
history names and this build's schema-shape digest are covered for the target
environment, and every project's release dispatch runs the rehearsal itself
when it finds either uncovered. Both ask the same question, because an entry that only
rewrites rows moves no schema shape — so a shape-only check reports the
riskiest entry as already covered.

Each tenant is copied in full even when its migration ledger has no pending
entry. A large `pg_dump` may run longer than an hour while its archive keeps
growing; the copy has no total time limit. If the archive stops growing for
five minutes, preflight kills the stalled copy, removes the partial archive,
and names the source database or SSH tunnel to check before rerunning. A
dropped tunnel still gets the existing connection recovery and retry path.

Fleet preflight and validation-copy rehearsal pass database passwords through
`PGPASSWORD` in each client's environment. Connection strings containing
passwords stay out of process arguments; fleet dumps use the shared libpq
environment mapping, while local copy clients name only the socket, user, and
database in their arguments. Dump failure diagnostics redact the password.

An `engine_tenants` fleet is tenant databases only. Names carrying the reserved
`yoke_test_run` scratch prefix are disposable by construction — a test or
rehearsal run created them and nothing owns them once it exits — so the
enumeration skips them and reports how many it skipped. Converging one
proves nothing about any tenant, and two strays on a cluster were once
enough to fail a release's rehearsal against the ledger of a run that had
already gone. The reported count is the signal to clean them up: the skip
keeps them out of the fleet, it does not hide that they are there.

Deep reference: [reference/db-reference.md](reference/db-reference.md),
`reference/db-reference/migration-model-capabilities.md`, and
`reference/db-reference/migration-model-fleet.md`.
