# Test database templates

`runtime.api.fixtures.file_test_db.init_test_db` builds each schema callable
once per pytest worker in an owned Postgres template database. Tests receive
a reusable clone whose schema, rows and sequences reset after each checkout.
The template never receives test writes. Nested contexts and replacements
after schema changes clone the template instead of replaying initialization.

Planner statistics belong to that baseline too. An `ANALYZE` or automatic
statistics update can change index choices even after rows are restored.
When relation estimates or column statistics drift, the existing reusable
clone is discarded and the next checkout rebuilds from the unchanged template.
Ordinary checkouts keep reusing their database. Session settings end with
their connection; database-scoped `ALTER DATABASE ... SET` changes still need
a separately disposable database.

Before first baseline capture, construction stops other connections to the
newly owned reusable clone, disables ordinary automatic maintenance on its
user tables, and commits that policy. Source templates, ambient databases,
independent disposable databases and global settings stay unchanged.
Wraparound protection remains active, and explicit `ANALYZE` still causes
baseline invalidation. Drift field names do not identify the initiating process.

Discard writes `reusable database invalidated:` to the captured stderr.
Its JSON distinguishes `schema` from `planner_statistics`; planner drift
lists relation and field names only, without values or connection strings.
Retain that evidence before diagnosing a reuse failure; it does not identify
whether a statistics change was requested or performed by maintenance.

The shared `test_db` fixture, the default strategy, explicit `schema.cmd_init`
and `apply_test_schema` use one production schema flavor. The template runs
`environment_bootstrap.run_init_chain`, including `schema.cmd_init`, then
adds baseline test projects and their development sites. Every production
trigger and constraint stays present; fixture code never copies the full DDL
or stamps migration history independently. `test_fixture_schema_ddl_apply.py`
compares every public trigger and table constraint with a freshly initialized
production database and checks the migration birth ledger. Verdict evidence
tests exercise the real binding under the immutable-verdict trigger.

Seed every foreign-key parent and required clock through the shared helpers.
When a real constraint exposes a runtime defect, fix the runtime operation;
removing a task must retire its file scope and bindings in the same transaction.
Session creation supplies explicit project authority; source CLI tests must map
the workspace or pass the resolved project ID to the lifecycle helper.

A flavor that only adds rows or tables to an existing schema starts from that
schema's template. Bind `seeded_schema(apply_test_schema, seed)` or
`seeded_schema(apply_booted_schema, seed)` at module level: its template is a
clone of the base template, and only `seed` runs when it is built. A fixture
that needs nothing beyond `schema.cmd_init` and the baseline test projects
uses the default flavor instead of rebuilding the same schema.
`apply_booted_schema` runs the production init chain without test seeds; use
it, or `booted_universe_database()` for a fresh disposable clone, where a test
needs a born universe rather than the test projects.

Other schema callables retain separate flavors by callable identity.
Different functions with the same name remain separate. Callable objects and
closures retain their identity for the worker's lifetime. Use a distinct
callable for different schema or seed inputs; do not change a callable's
captured inputs between checkouts and expect the template to change.

Pass a module-level schema function, not a new lambda or nested function on
every checkout. A fresh callable is a distinct flavor even when its source
is identical. `apply_empty_schema` provides a stable blank flavor for tests
that intentionally create their own tables. A bounded schema factory may
cache explicit immutable inputs, such as the presence of projects/items tables;
never infer equivalence from callable source text.

Behavior fixtures use `pg_testdb.test_database()` or `init_test_db()` and seed
the case after checkout. The context owns its connection, database reset and
ambient DSN restoration. Do not add a redundant `monkeypatch.setenv` for that
same DSN: fixture teardown could restore an already-exited checkout. Tests
that deliberately alter ambient authority use an inner `monkeypatch.context()`
so those changes unwind before the database context. Unittest cases can use
`self.enterContext(pg_testdb.test_database())` to guarantee cleanup on failure.

Fresh initialization remains intentional in schema/boot/migration/restore
coverage. `test_fixture_schema_ddl_apply.py` compares a fresh production build
with the shared template; `test_pg_testdb.py` exercises initialization itself.
Local callbacks in boot, schema-order and custom-strategy tests retain their
fresh invocation when that invocation or its captured observations are the
subject of the test. Migration fixtures may cache their initial schema while
applying the migration under test after checkout. Path-snapshot and pipeline
fixtures cache only DDL; repository paths, machine mappings and case-specific
project settings are seeded on the checked-out database.

Keep machine-local setup outside the schema callable. For example, a fixture
that registers sessions records its operating actor in each test's redirected
machine home after checkout, using `record_fixture_operating_actor` for its
already-seeded human. Cloning
schema and rows does not copy machine configuration or replay other setup
side effects.

Audit transitive schema consumers too: a helper may be called from another
module's cached strategy. Shared session connection helpers bind the actor
after connecting; schema builders seed only database rows. Regression checks
reuse the exact same callback with several fresh machine homes in shuffled
order, including session, stale-session, driver-stamp, field-note and concurrent
claim fixtures. Check imports and aliases when tracing shared schema builders;
consumer filenames need not contain the schema's domain name.

A failed template build drops its database and restores the prior DSN before
raising the schema failure. Fix that schema strategy and retry; the failed
build is never retained. Worker exit drops templates and reusable databases.
The existing invocation namespace keeps concurrent runs separate.

Merge subprocess tests also copy an origin, repository and linked worktree
built once per test module. Each copy rewrites its Git pointers and origin
URL to its own directory. Automatic maintenance and garbage collection are
disabled in the template's repository and bare origin so a background Git
process cannot change files while the template is copied. Database setup
uses the booted template — the complete production init chain, including
domain tables such as `item_dependencies`; `schema.cmd_init` alone supplies
only the shared core. Per-test project, machine and merge-item seeds
still use each test's paths.

Use the watcher for focused checks and record CI's shard wall times when
comparing performance. A green fixture check proves isolation and reuse;
it does not establish the full CI runtime reduction.
