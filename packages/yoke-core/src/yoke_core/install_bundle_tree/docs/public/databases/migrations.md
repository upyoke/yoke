# Database migration conventions

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Databases](index.md) > Migration conventions
<!-- /yoke:breadcrumbs -->

Use the timestamp, query-clock and migration-audit conventions when authoring or applying governed migrations.

## Timestamp discipline

PostgreSQL instant columns use `TIMESTAMPTZ`; Python retains aware datetimes.
Nullable instants use SQL NULL. The classified roster and serving catalog own
storage declarations; permanent history owns governed conversion.

Application writers bind `instant_parameter(conn, utc_now())` or a supplied
`parse_instant(value)`. Owned wire, JSON, file and SQLite values use canonical
UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ` and permitted nulls. Format with
`format_instant` or the shared JSON encoder at those boundaries. Calendar dates
and opaque strings keep their own contracts. Read [domain instants](../reference/timestamps.md)
for the shared kernel, strict input, historical conversion and wire recipes.

## Query-Time SQL Clock Helpers

`yoke_contracts.time_sql.now_sql(...)` supplies native indexed predicates;
fixed day/hour/minute offsets count elapsed seconds. Trusted `offset_modifier`
SQL has caller-owned calendar meaning; board buckets declare their timezone.
Python cutoffs bind through `instant_parameter`. `instant_wire_sql(expression)`
projects canonical fixed-six UTC text after native filtering and ordering,
preserving SQL NULL. See [domain instants](../reference/timestamps.md) for query examples.

## `migration_model` capability — recipe + runner vocabulary

Validation recipes and migration runners live behind the `migration_model`
row, each model's release fleet behind the `migration_fleet` row: vocabulary,
pairing matrix, and webapp Pack contract in
[model declaration and runner](migration-model.md) and
[audit, pairing and Webapp Packs](migration-model-pairing.md);
the fleet in [migration fleets](migration-fleet.md).

## Live-apply provenance on `migration_audit`

A destructive apply refuses rather than writing nulls: session, actor, branch,
and commit must be established first, and the receipt records them. Legacy
null rows stay as incident evidence and are not backfilled. `model_name` is a
declared migration model; an execution level in that column is refused.

The extra provenance columns below remain nullable so older rows stay
readable. `set_audit_provenance` still skips unknown columns on a
pre-migration authoritative DB.

```sql
actor_id          TEXT  -- harness_sessions.actor_id at apply time
worktree          TEXT  -- absolute worktree_path the apply ran from
source_branch    TEXT  -- git branch in that worktree (--show-current)
source_commit    TEXT  -- git HEAD sha in that worktree
integration_target TEXT -- typically 'main'
change_class      TEXT  -- profile.migration_strategy (additive_only, hard_cutover, expand_contract)
```

The `migration_audit.lease_id` join already linked the audit row to the coordination claim that protected it; the new columns answer "from which checkout, by which actor, against which integration target." Doctor's `coordination-claims-unmerged-source` HC uses `source_branch` + `integration_target` to flag completed rows whose source never reached integration target — a sign the worktree was deleted before the slice merged.

## Applying a migration

There is no apply command. A server brings its own database up to the code it
runs before it serves: `converge_core_schema` computes `history - ledger`,
takes an exclusive per-database advisory lock, and applies each pending entry
in order, committing the entry and its raw-byte SHA256 in the
`applied_migrations` row in ONE transaction. A common non-NULL digest mismatch
refuses before restore or mutation. Legacy NULL rows remain serviceable but are
reported for explicit manifest-bound adoption; the mandatory prepare/verify/
apply procedure lives in
[migration-model.md](migration-model.md).
`/v1/health` reports `migration_content_evidence_ready` and refuses serving
when the evidence schema or exact append-only guard behavior is not intact;
container/deploy readiness also requires the adoption-required list to be empty.
Boot is fail-hard, so a container never serves behind its schema or against
known mismatched permanent migration bytes.

A work item authors the entry and rehearses it:

```bash
yoke --env <name> dev run -- yoke migration rehearse PREFIX-N
```

Rehearsal applies the entry to the validation surface, records the gate's
receipt in `migration_audit` on the control plane that holds the item, and
holds the `LIVE_DB_MIGRATION:<model>` coordination claim until the merge lands so
a second item cannot enter migration territory meanwhile; failure releases it.

## Related

- [Reference](reference.md)
