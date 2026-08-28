"""Capability-shaped teaching for control-plane connections.

A capability taught only through its restriction is lost at the moment it
is needed. These strings state what each connection kind is for alongside
what it is not. They do not change who may use a path or when.
"""

from __future__ import annotations

# Shown when `yoke db` lists only `read` — the refusal that previously
# read as "no write path exists anywhere."
DB_GROUP_TEACHING = """\
`yoke db` is read-only diagnostic SQL over the active connection.
Ordinary writes use registered `yoke <subcommand>` surfaces.
A one-off SQL write that no registered command covers is break-glass:
`python3 -m yoke_core.cli.db_router query "SQL"`
under `--env <https-env>-db-admin` on that local-Postgres admin
connection. The path stays
source-dev/operator-debug; it is not missing, and it is not the
agent default. `yoke env list` shows which admin connection this
machine has.
"""

# Compact session-packet stanza: kinds of authority, not a config dump.
CONNECTION_AUTHORITY_STANZA = (
    "Connection authority: `yoke env list` prints every configured "
    "connection (name, active, transport, prod). HTTPS is the normal "
    "product/API authority — registered `yoke` commands relay there; "
    "it has no local SQL write. A local-Postgres `*-db-admin` "
    "connection is direct database authority for sanctioned "
    "source-dev/admin and audited break-glass SQL "
    "(`python3 -m yoke_core.cli.db_router query` under "
    "`--env NAME`). `yoke db` is read-only; that admin path "
    "is the escape hatch, not a missing write command. Ordinary "
    "writes use registered `yoke <subcommand>`."
)

# Human footer on `yoke env list`. JSON inventory stays sanitized rows.
ENV_LIST_AUTHORITY_FOOTER = (
    "https = normal product/API authority (registered yoke commands; "
    "no local SQL write). local-postgres = direct database authority "
    "on a *-db-admin connection: sanctioned source-dev/admin and "
    "audited break-glass SQL via "
    "`python3 -m yoke_core.cli.db_router query` under "
    "`--env NAME`. `yoke db` stays read-only."
)


__all__ = [
    "CONNECTION_AUTHORITY_STANZA",
    "DB_GROUP_TEACHING",
    "ENV_LIST_AUTHORITY_FOOTER",
]
