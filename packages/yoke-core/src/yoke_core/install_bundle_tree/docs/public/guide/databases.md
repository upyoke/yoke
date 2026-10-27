# Databases and migrations

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Databases and migrations
<!-- /yoke:breadcrumbs -->

Yoke can bring database changes into your project's delivery process, with migration rehearsals, compatibility checks, and records of what was applied. Your project must configure the database connection and migration integration it needs; installing Yoke does not automatically grant agents access to application data.

During `/yoke onboard`, your agent can register database and migration settings or defer them. Onboarding itself does not apply or rehearse migrations. Once the required integration is ready, agents can rehearse changes before release.

## Database configuration

### Project databases and the Universe database

Your Yoke Universe stores projects, work items, strategy, and other Yoke records. Your application's database stores the data your software uses. These are separate responsibilities, even when both use PostgreSQL.

A model names a database and its governed migration configuration. SQLite and PostgreSQL have different validation and access arrangements. Do not copy Yoke's own database settings into an unrelated project.

### Onboarding choices

Onboarding offers three choices: declare the database now, attach it later, or record that no governed database is needed. Declaring now saves the project's actual configuration and reads it back. Deferring records the missing information rather than inventing a connection.

The declaration alone does not provision every credential, validation database, migration module, or deployment integration. Your agent can help complete that project-specific work. See [Installation and setup](setup.install.md).

## Database access

### Connections and credentials

Database access needs a reachable target and credentials with the intended permissions. Configure the connection for the correct project and environment. An administrator connection for Yoke's own database is not a connection to your application's database.

The supported project PostgreSQL admin setup reads the declared database location and its environment's infrastructure settings. That path expects the corresponding endpoint, managed-secret, and network configuration; it is not an automatic connector for every database provider.

### Agent diagnostics and read-only access

Through a configured diagnostic connection, `yoke db read` runs bounded read-only queries. Its query restrictions prevent writes through that command; they do not mean the underlying account has no write privileges. Choose credentials and network access appropriate to the work as well as using the correct command.

The ordinary HTTPS control-plane connection addresses Yoke's records. An application's database needs its own supported connection or project-specific tooling. Ask your agent to identify the target explicitly before inspecting it. [Database reference](../databases/reference.md)

## Migration models

A migration model declares the authoritative database, validation surface, and migration runner. Its settings identify the project-relative migration directory, connection environment variable, and ledger used to record applied entries.

The supported governed runner executes permanent Python migration modules. A module applies its change and may define invariants to check afterward. Projects using another migration system need deliberate integration rather than assuming the system is automatically governed by a declaration.

SQLite models can use a worktree-local validation database. PostgreSQL models use an externally prepared validation database. The validation connection must identify the test copy, not the authoritative database.

The project also integrates application into its boot or deployment process. Yoke's model does not independently know how every external application starts or changes its schema. [Migration model contract](../databases/migration-model.md) and [model pairing](../databases/migration-model-pairing.md)

## Governed migrations

### DB claims and permanent history

An item's DB claim states whether it changes a governed database. Migration entries form an ordered, permanent history. Add new entries to correct earlier behavior rather than editing an entry that a database has already applied.

Under the governed contract, additive schema can converge during boot, while changes such as backfills, rewrites, and removals belong in migration history. The project must implement that contract; it is not a claim about arbitrary database frameworks.

### Compatibility and invariants

Compatibility attestations describe the change's relationship to readers and writers. Serving floors prevent a build that is too old for the migrated schema from starting as though it were compatible.

Invariants are lasting assertions about what a migration guarantees. They must continue to hold as ordinary application writes occur. A temporary row count or an incidental post-migration value is usually not such a guarantee.

### Restore points and apply records

Destructive changes need a named restore point. Apply records retain which entry ran, its content identity, and its outcome. A recorded successful rehearsal proves the rehearsed target; it is not evidence that a live database was already updated. [Governed migration reference](../databases/index.md)

## Migration rehearsal

Prepare a separate validation database with the schema and data shape needed to exercise the migration. Provisioning is project-specific, especially for an existing PostgreSQL application. Merely creating an empty database may miss the conditions the change must handle.

An item rehearsal runs its declared migration modules and verification against that validation surface. It records evidence and uses migration leases to coordinate conflicting work. Correct a failed migration, refresh the validation surface as appropriate, and rehearse again; do not substitute an ad hoc write against Production.

The eventual live apply follows the configured boot or release path. [Rehearsal configuration](../databases/migration-model.md)

## Migration fleets

A fleet declares the live databases a release must rehearse. It can cover a single database or several; it is not limited to multi-database projects.

The current copy-based path supports PostgreSQL databases reachable through the environment's configured admin connection. Named-database fleets provide the database names and the project's convergence and verification commands. Yoke's engine-tenant fleet is a separate built-in arrangement for its own tenant databases.

Preflight reads each source database, restores a temporary local copy, runs the declared convergence and verification, and removes the copy. It does not change the original. A passing release receipt records which migration history and schema shape were covered for that model and environment.

An unsupported target needs an explicit declaration explaining why it has no copy-based fleet. This is distinct from silently omitting the setup, and it does not supply evidence that a rehearsal happened. [Fleet declarations and limits](../databases/migration-fleet.md)

## Diagnostics and data repair

Read-only diagnostics can investigate a problem without changing the selected database. Repairing data is a separate operation with its own authority and review.

Yoke's reviewed operator repair command repairs bounded Yoke records when ordinary domain commands cannot express the correction. It requires authorized steering, a reviewed change document, and a simulation of the expected before and after values. It is not a general repair service for arbitrary application databases.

Application data repairs belong to the project's own controlled tooling or governed migration process. Preserve the reason, review, restore point where required, and evidence of what changed. [Operator repair contract](../databases/operator-data-repair.md)

Machine-local logs and rehearsal captures may need retrieval from the machine that produced them. They are diagnostic evidence, not a replacement for durable migration or repair records. [Machine-local evidence](../databases/machine-local-evidence.md)
