# Migration entry test coverage

`runtime/api/domain/test_migration_entry_contract.py` owns the shared contract
for every executable entry discovered by `ordered_entries()`: load through the production
loader, require a serving floor for destructive entries, apply twice, and check
standing invariants through the fleet re-prover. It runs against an empty
booted universe and a current schema with test projects, using the existing
schema templates in `migration_boot_test_helpers.py`.

An empty universe has today's additive schema before boot stamps history;
a bare connection without that schema is not an existing-universe replay target.
The shared harness uses the production invariant retirement
rules so frozen historical assertions do not demand surfaces later entries removed.
The boot tests separately prove pending-history application and ledger recording.
Migration-area impact companions select both shared checks when an entry changes.

Dedicated entry tests hold data-change and refusal assertions for entries that
an installed database can still reach. Do not duplicate the shared floor,
empty-universe or generic replay checks there. Preserve rerun assertions that
prove a specific data fold preserves row values or identity.

Before retiring old dedicated coverage, check the hosted and local ledgers and
account for every known self-hosted install. Applied entries remain immutable
history; removing their tests does not remove their files or authorize replay
changes. The historical tests through entry 0098 were retired after hosted
production and stage showed every entry through 0102 applied, local convergence
reached 0099, and the operator confirmed there were no self-hosted installs.
Later entry-specific assertions remain until their reachable-install proof exists.

When a verified predecessor history is replaced with a code-declared baseline,
retire its dedicated tests in the same change. The entry-test policy rejects
references to absent numbered modules and explicit history-loader entry or slug
selectors. Engine tests may keep historical names as inert fixture data.

The control plane now declares `0106_baseline` without a migration script.
All eight hosted ledgers hold only baseline membership, so the temporary
transition input and boot ledger rewrite have been removed. Births write only
baseline membership; the shared script replay test continues to discover
future entries after ordinal 0106. Baseline tests cover birth, missing
membership refusal, repeat boot, wheel identity and later migration
application. Runtime modules cannot import migration scripts; the source guard
enforces that boundary in both directions.

After ledger collapse, rollback below the carrying release is unsupported.
See [the baseline decision](../archive/decisions/control-plane-ledger-baseline.md)
for the two-release transition and removal of old archive import adapters.
