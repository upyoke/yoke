# Database authority and governed mutation

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Databases
<!-- /yoke:breadcrumbs -->

## Control-plane authority

- The control plane uses Postgres. Use `yoke <subcommand>` and `yoke db read "SELECT ..."`;
  never invent DB paths or use worktrees as control planes. `yoke env list` lists connections.
  Missing mutations: ask the control-plane operator.
- Raw item reads join `item_refs r ON r.item_id = items.id` and select `r.public_ref`.
- Read one scalar setting at a time:
  `yoke projects environment-settings get --project P --environment E --path KEY.PATH`.
- Code and tests use model validation (`model.runner.connection_env_var`,
  default `YOKE_DB`); control-plane commands use `CANONICAL_YOKE_DB`. Client code relays to the
  control plane and never connects; code that truly owns a local database declares
  `local_authority_exempt()` at the call site. Converge and apply refuse on a prod-flagged
  connection unless the serving build declares `serving_build_authority()` at the call site.

## Governed DB mutation

Applies to projects with a `migration_model` capability.
Model: [databases](../../databases/index.md).

- Write the item's DB claim only through `db_claim.amend`
  ([DB claim](../../items/model/items.md#db-claim-the-unified-amendment-workflow)).
- Net-new tables and columns go in the schema module; boot converges them. No migration needed.
- Drops, backfills, rewrites and bulk data on a declared authoritative DB go only through the
  ordered migration history. Never run ad hoc write SQL there. A new audit-fingerprint
  exception call site needs `docs/archive/decisions/<helper-name>.md` and `exception_reason`.
- Bounded row repairs use `yoke operator data-repair --dry-run` from a live steering seat after
  the operator approves the digest ([data repair](../../databases/operator-data-repair.md)).
- Items author and rehearse; boot applies. A new entry takes the next number. A destructive
  entry sets `MINIMUM_SERVING_VERSION = "next-release"`, never a literal version.
- Never edit an applied entry. Retire a wrong invariant in a new entry (`RETIRES_INVARIANTS`).
- A destructive apply needs a named restore point; the applier refuses without one.
- Rows under a digest or immutability guarantee use the readers' canonical serializer.
- A row-transforming entry is idempotent when its output already exists: fold, do not recreate.
- Rehearse with `yoke migration rehearse PREFIX-N` from the configured local-Postgres authority
  that owns the item; with none configured, escalate. It holds `LIVE_DB_MIGRATION:<model>`
  until the merge lands. From a source lane: `yoke dev run [--lane <path>] -- yoke --env <name>
  migration rehearse PREFIX-N` (`--env` before `dev run` is refused). `rehearsal_commands` are
  tests, never the rehearse command.
- Several items with entries: assign ordinals, stack each lane on the previous branch, list every
  module on the top item's DB claim, rehearse once on the top item, land in order, ship in one
  release.
- Before a release carrying an unapplied entry, run
  `yoke watch preflight -- --project P [--model M] <environment>`; the release refuses without
  that environment's receipt ([migration fleet](../../databases/migration-fleet.md)).
- Pick `migration_strategy` per the project's `breakage_policy`: `hard_cutover` under
  `compatibility_required`, or `expand_contract` under `founder_cutover`, needs a
  `migration_strategy_justification`. `compatibility_class` is a separate axis; never relax it
  silently ([DB claim](../../items/model/items.md#db-claim-the-unified-amendment-workflow)).
- Before releasing a stranded migration lease, read
  [stranded lease recovery](../../sessions/model/coordination.md#stranded-migration-lease-recovery).

## Related

- [Operating with agents](../index.md)
- [Agent operation homes](index.md)
