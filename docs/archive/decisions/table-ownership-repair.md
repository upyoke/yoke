# Table ownership is repaired outside the governed migration path

`migration_fleet_ownership.realign` issues `ALTER TABLE ... OWNER TO` against a
live authoritative database. That is write DDL outside the ordered migration
history, so it needs saying why.

## What it is not

It transforms no rows, adds and drops no columns or tables, and changes no data
a reader can observe. It corrects *who owns* a table. Nothing about the shape
of the database differs before and after; what differs is whether the serving
role is permitted to converge it.

It is also not automatic. Nothing in a deploy, a boot, or a lifecycle
transition calls it. It runs when an operator names a database, passes
`--apply`, and names each table individually — a blanket repair is refused,
because a differently-owned table is not automatically wrong and a separately
provisioned surface may legitimately own its own.

The one call site that is not an operator typing a command is the migration
applier handing back a table it has just created itself, which is narrower
still: it realigns only the two tables that tool can bring into existence, and
only when they disagree with the majority owner.

## Why it cannot be a migration entry

A migration entry runs during the boot converge, as the serving role. That role
is precisely the one that lacks permission — the whole failure is that it does
not own the table. An entry attempting the repair would be denied by the same
privilege check it exists to fix.

The repair therefore has to run as a role that *can* alter the table, which is
the admin connection, which is not a boot path. There is no ordering in the
history that changes this.

## Why it has to exist at all

A boot converge adds columns to its own tables. A table created by another role
can never afterwards gain a column, so it is a boot failure waiting for the
next release that touches it — arbitrarily later, with nothing connecting the
two changes. The error reads like a missing column, because Postgres resolves
identifiers before it checks privileges, which sends the reader looking for the
wrong defect.

One instance took a production control plane down for twenty-five minutes. The
table had been created months earlier by an operator running a repair through
an admin connection, and nothing at the time indicated that doing so had
permanently removed the server's ability to converge its own ledger.

## The rule this establishes

Any tool that creates a table on a tenant database hands it to the serving
role, or it has left a trap. The applier now does this for the tables it
creates. Detection lives with the fleet preflight, which reads ownership from
the live database because a `pg_restore --no-owner` copy cannot show it.
