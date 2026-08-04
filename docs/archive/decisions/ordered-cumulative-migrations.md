# Ordered cumulative migrations

Migrations are an ordered, permanent, in-repo history. Each database records
what it has applied in its own ledger. Every boot applies whatever is pending.
Completion is derived, not tracked.

## What this replaced, and why

Migrations used to be ephemeral: author a module, apply it by hand, delete the
source. Every mechanism around them existed to compensate for that inversion —
applied-everywhere deletion evidence, install-topology declarations,
auto-retire, manifest dispatch, a cross-worktree module override.

It produced a real incident. On 2026-08-02 a set of drops reached only the
prod universe before auto-retire deleted the sources; the stage universe and
the hosted tenants silently kept the retired columns until a manual
`information_schema` diff found them a day later. Nothing could have noticed:
the modules were gone, so no install could compute what it still owed.

Rails, Django, Flyway and Alembic cannot have that bug, and not because their
operators are more careful. The history is permanent, so "what do I still owe?"
is always answerable; the ledger is per-database, so the answer is per-database;
and the apply is on the deploy path, so nobody has to remember to run it.

## The shape

- **History** — `packages/yoke-core/src/yoke_core/domain/migrations/NNNN_slug.py`,
  ordered by the numeric prefix, never deleted. The filename stem is the entry's
  only identity; there is deliberately no second name to disagree with it.
- **Ledger** — `applied_migrations(migration_name, applied_at, applied_by)` on
  every governed database. A cursor, not a receipt store.
- **Pending set** — `history - ledger`, computable from the installed wheel plus
  one connection.
- **Applier** — the tail of `converge_core_schema`. Probes cheaply; on a
  non-empty pending set takes an exclusive per-database advisory lock,
  re-enumerates under it, and applies each entry in order.
- **Health** — `migrations_current` on `/v1/health`, plus
  `HC-pending-migrations`.

## Decisions worth keeping

**Apply and ledger commit in ONE transaction.** Postgres has transactional DDL,
so the "applied but unrecorded" state that forces other tools to ship repair
tooling cannot occur. This is why a module must not commit inside `apply()` —
doing so splits that transaction and gives the guarantee back.

**Membership by name, not head equality.** A rolled-back container runs older
packaged code than its database has applied. By name it is current, which is
true. Head equality would call it broken and refuse to serve, bricking the
rollback direction as well as the forward one.

**Birth is a caller-observed fact.** `cmd_init` runs the converge FIRST, so
after the creation steps a newborn database and a pre-ledger one look identical
— both have an empty ledger and current-looking schema. Born-ness is therefore
read before anything is created (`universe_is_born_on`, the org-card sentinel)
and carried down. A newborn stamps the history; an existing database applies it.

**Two locks at two layers, and they do not substitute.** The applier's
per-database advisory lock is *execution* serialization: two servers must not
migrate one database at once. The `LIVE_DB_MIGRATION:<model>` coordination lease
is *workflow* serialization: a second work item must not enter migration
territory while one is in flight. The lease moved onto rehearsal and is HELD
past the call, because the window it must cover is "from starting a migration
until it lands", not "while a command runs".

**Boot-apply never touches the control plane.** A booting tenant that depended
on the control plane would turn a control-plane outage into a fleet-wide boot
outage. The consequence, stated so nobody later reads it as a bug: the
coordination lease cannot see a fleet roll in flight. That collision is safe
anyway — a rolling container applies the history that shipped in *its* wheel,
which is immutable. The collision that does bite, two items claiming one
sequence number, is caught by the history validator rejecting duplicates.

**Never apply without a named restore point.** Local and self-hosted installs
dump; a hosted fleet names the managed cluster's continuous point-in-time
window. The `migration_audit` receipt records which restore point covers the
apply, so recovery after a failure is a lookup rather than a reconstruction.
A per-tenant dump at container boot was rejected deliberately: on a large tenant
it runs past the deploy health window, and it writes into the container that is
about to be replaced.

**An entry must finish, not fail.** The stage-vocabulary entry pinned
`WORKFLOW_SCHEMA_VERSION = 3` and rejected anything else. The codec moved to 4,
and `converge_builtin_workflows` seeds current-version definitions *before* the
history runs in the same converge — so the entry asserted against data the same
boot had just written. Because the ledger starts empty everywhere, it was
pending on every universe, and boot is fail-hard: as written it would have
crash-looped every container on the first roll. A permanent entry outlives the
shape it was written against, so "already at or beyond my target" is finished,
not an error.

**An entry that is done writes nothing.** The same entry rewrote every
`workflow_versions` row unconditionally — published, immutable, digest-guarded
rows — and suspended their immutability trigger to do it. It also serialized
with `dumps_compact` rather than the registry's `canonical_definition_json`
(sorted keys, `ensure_ascii=False`), so it stored bytes no other writer would
produce. A published definition whose digest stops matching the code-owned one
is a startup abort; that exact failure mode took the fleet down. Any entry
rewriting rows under a digest or immutability guarantee must use the same
canonical serializer its readers use, and must write only rows that change.

## What the evidence gate asks now

Leaving `implementing` used to require a completed audit row for an operator
apply. Under boot-driven apply that is evidence from the future — the apply
happens after the item merges. The gate now asks for what the item can
produce: the declared
module is IN the history, correctly named and loadable, and a rehearsal receipt
exists. A runner with no checkout cannot read the history directory; that is
"cannot inspect", not "missing", and the rehearsal receipt still applies.

## Deploy-before-drop, enforced at the seam that now exists

Membership by name is what makes rollback possible, and it is also what makes a
rolled-back container dangerous: its history does not contain the newer
destructive entry at all, so it computes an empty pending set, reports
`migrations_current` true, and serves broken reads against columns that are
gone. Head equality would catch that and brick rollback in both directions,
which is worse. The ordering rule therefore moved rather than disappeared.

A destructive entry declares `MINIMUM_SERVING_VERSION`: the oldest artifact
version that may serve against a database once the entry has been applied. An
entry that removes a surface without declaring one fails at module load, which
is the path every apply route goes through, so the declaration cannot be
skipped by taking a different one. The applier refuses to run an entry whose
floor is newer than the build running it.

**The declaration is copied into the ledger row at apply time.** That is the
whole mechanism: the reader who needs it is a build old enough to be stranded,
and such a build does not ship the entry module that would tell it so. The
ledger row is the only surface the two share. `/v1/health` reads it back and
answers `can_serve_this_database`, naming each offending entry — which is what
converts a silent broken-read outage into a container that fails its own health
gate.

Three states are deliberately not violations, because each would otherwise
manufacture a fleet-wide refusal out of missing information. A row with no
recorded floor is *unknown*, not unsafe — it is the majority state on any
database that applied anything before floors were recorded. An unresolved
running version is a source checkout, which advertises its last tag rather than
its code and is ahead of the entry it carries, not behind it. An unreadable
ledger returns no findings, inverting the pending-set probe's fail-closed
stance on purpose: "am I current?" must read cannot-tell as no, while "am I
forbidden from serving?" must not.

Rollout overlap turned out not to exist. A tenant is one container plus its own
database, rolled together and health-gated before the fleet walk continues, so
neither two builds of one tenant nor one tenant's drop reaching another is
possible. The exposure is a *completed* roll or rollback that leaves a tenant
on a build too old for its own database, which is exactly what the health
answer catches.

## Squash policy

Entries may be folded into the baseline schema once every known install's ledger
is verifiably past them — evidenced by fleet-wide `HC-pending-migrations` green.
Birth stamping keeps working because it stamps whatever history exists.

## Not folded in

`schema_init_columns.apply_legacy_data_migrations` is the pre-existing,
unledgered pile of one-off data migrations that runs only on the full-init
chain. It stays as it is; it has run everywhere and is idempotent. The forward
rule is that new data-transforming changes go in the ordered history, and
nothing further is appended there.

The same rule applies to `converge_platform_schema`'s inline repairs in the
Platform repo — the constraint drop/re-add, the `DROP NOT NULL`, the backfill
updates. Settled, idempotent, left alone; new destructive changes go to the
registry's own history.

buzz is a documented exception on the merits: it is a separate product outside
the Yoke/Platform release train, on SQLite, and it already implements this
design independently (ordered `NNN_` modules, a `schema_version` ledger, apply
on boot in its entrypoint). Rewriting working code to share a Postgres-shaped
kernel would be churn, not coverage.
