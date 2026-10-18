# Repair the local connection

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Local connection repair
<!-- /yoke:breadcrumbs -->

```bash
yoke init --local
yoke doctor run --only connections --project P
```

Replace `P` with your project. Init starts and verifies this machine's owned
Postgres cluster. It repairs a missing local DSN file or an operating actor
recorded for another universe without `--force`, and reports each repair.
It also re-records an actor that no longer exists in that universe.
Existing projects, items and settings stay in the owned cluster.

Init preserves the active connection, including when `--force` rewrites the
local entry. It selects local automatically only when no connection is active.
To select local explicitly during initialization:

```bash
yoke init --local --activate
```

A readable connection pointing elsewhere, a connection using HTTPS, or a
production-marked entry still requires explicit replacement:

```bash
yoke init --local --force
```

Inspect and back up that connection's universe before replacing its machine
record. `--force` replaces the connection record; it does not select it or
replace the owned local database. Add `--activate` to select local too.
A new universe also needs `--admin-name "Your Name"` for its first admin.

Doctor's `connections` check runs on this machine in local, self-hosted and
hosted mode. It reports `CONNECTION_CREDENTIAL_FILE_MISSING` for missing
credential files and `CONNECTION_OPERATING_ACTOR_INVALID` for actors that
are missing, invalid, or bound to another universe. It opens each direct
connection with a read-only transaction and never changes the selected
connection or its binding. An unreachable database produces
`CONNECTION_ACTOR_UNVERIFIED`, with a step to retry after restoring access.

For `connections.local`, the repair is `yoke init --local`. For another
connection, Doctor names setup under that connection's explicit `--env`.
If the active connection is broken, Doctor reports the connection findings
before trying to use it; `doctor_active_connection_unavailable` means the
rest of the requested scope still needs a rerun after repair.

See [Modes](../start/modes.md#local) and [Machine config](../cli/machine-config.md#machine-config).
